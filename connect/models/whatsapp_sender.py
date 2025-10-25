# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import json
import requests
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class ConnectWhatsappSender(models.Model):
    _name = 'connect.whatsapp_sender'
    _description = 'Twilio WhatsApp Sender'
    _rec_name = 'number'
    _order = 'number'

    # Core identifiers
    sid = fields.Char(string='SID', index=True, readonly=True)
    number = fields.Char(required=True, help="Sender phone in E.164, e.g., +1234567890", readonly=True)
    status = fields.Char(readonly=True)
    url = fields.Char(readonly=True)
    offline_reasons = fields.Text(readonly=True)

    # Convenience fields
    number_id = fields.Many2one('connect.number', string='Linked Number', ondelete='set null',
                                help='Matched by phone number if available.', readonly=True)

    # Profile
    profile_name = fields.Char(string='Business Name', readonly=True)
    profile_about = fields.Char(string='About', readonly=True)
    profile_vertical = fields.Char(string='Vertical', readonly=True)
    profile_address = fields.Char(string='Address', readonly=True)
    profile_description = fields.Text(string='Description', readonly=True)

    # Messaging webhooks (computed)
    callback_method = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
    ], compute='_get_twilio_urls', compute_sudo=True)
    callback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    status_callback_method = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
    ], compute='_get_twilio_urls', compute_sudo=True)
    status_callback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)

    # Properties
    messaging_limit = fields.Char(string='Messaging Limit', readonly=True)
    quality_rating = fields.Char(string='Quality Rating', readonly=True)
    _sql_constraints = [
        ('sid_unique', 'UNIQUE(sid)', 'This Sender SID already exists!'),
        ('number_unique', 'UNIQUE(number)', 'This number already exists!'),
    ]

    @api.onchange('number')
    def _onchange_number(self):
        for rec in self:
            num = self.env['connect.settings'].strip_number(rec.number) if hasattr(self.env['connect.settings'], 'strip_number') else rec.number
            candidate = f"+{num}" if num and not str(num).startswith('+') else num
            linked = self.env['connect.number'].search([('phone_number', '=', candidate)], limit=1)
            rec.number_id = linked.id if linked else False

    def _prepare_vals_from_api(self, data):
        profile = data.get('profile') or {}
        properties = data.get('properties') or {}
        vals = {
            'sid': data.get('sid'),
            'status': data.get('status'),
            'url': data.get('url'),
            'offline_reasons': json.dumps(data.get('offline_reasons')) if isinstance(data.get('offline_reasons'), (dict, list)) else data.get('offline_reasons'),
            'profile_name': profile.get('name'),
            'profile_about': profile.get('about'),
            'profile_vertical': profile.get('vertical'),
            'profile_address': profile.get('address'),
            'profile_description': profile.get('description'),
            'messaging_limit': properties.get('messaging_limit'),
            'quality_rating': properties.get('quality_rating'),
        }
        sender_id = data.get('sender_id')
        if sender_id and isinstance(sender_id, str) and sender_id.startswith('whatsapp:'):
            vals['number'] = sender_id.replace('whatsapp:', '', 1)
        # Link number if exists
        if vals.get('number'):
            linked = self.env['connect.number'].search([('phone_number', '=', vals['number'])], limit=1)
            if linked:
                vals['number_id'] = linked.id
        return vals

    def _get_twilio_urls(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        edge = self.env['connect.settings'].get_param('twilio_edge')
        for rec in self:
            rec.callback_method = 'POST'
            rec.status_callback_method = 'POST'
            rec.callback_url = urljoin(api_url, f'twilio/webhook/message#e={edge}')
            rec.status_callback_url = urljoin(api_url, f'twilio/webhook/message_status#e={edge}')

    @api.model
    def sync(self):
        settings = self.env['connect.settings']
        account_sid = settings.get_param('account_sid')
        auth_token = settings.get_param('auth_token')
        if not account_sid or not auth_token:
            raise ValidationError('Twilio credentials are not configured.')
        url = 'https://messaging.twilio.com/v2/Channels/Senders'
        try:
            resp = requests.get(url, params={'Channel': 'whatsapp'}, auth=(account_sid, auth_token), timeout=30)
            if resp.status_code >= 400:
                raise ValidationError(f"Twilio error: {resp.status_code} {resp.text}")
            data = resp.json()
            items = data.get('senders', [])
            for item in items:
                vals = self._prepare_vals_from_api(item)
                # Upsert by sid if present, else by number
                rec = self.search([('sid', '=', vals.get('sid'))]) if vals.get('sid') else self.browse()
                if not rec and vals.get('number'):
                    rec = self.search([('number', '=', vals['number'])])
                if rec:
                    rec.write(vals)
                else:
                    rec = self.create([vals])[0]
                # Update sender webhook endpoints in Twilio
                try:
                    sid = rec.sid or item.get('sid')
                    if sid:
                        update_url = f'https://messaging.twilio.com/v2/Channels/Senders/{sid}'
                        payload = {
                            'webhook': {
                                'callback_method': rec.callback_method or 'POST',
                                'callback_url': rec.callback_url,
                                'status_callback_method': rec.status_callback_method or 'POST',
                                'status_callback_url': rec.status_callback_url,
                            }
                        }
                        resp_u = requests.post(update_url, auth=(account_sid, auth_token), json=payload, timeout=30)
                        if resp_u.status_code >= 400:
                            logger.warning('Failed to update sender %s: %s %s', sid, resp_u.status_code, resp_u.text)
                except Exception as e:
                    logger.warning('Sender webhook update error: %s', e)
            settings.connect_notify('WhatsApp Senders synced')
        except Exception as e:
            raise ValidationError(f"Failed to sync WhatsApp Senders: {e}")

    def action_sync(self):
        self.ensure_one()
        self.env['connect.whatsapp_sender'].sync()
        return True

    @api.model
    def update_message_status(self, data: dict):
        """Update connect.message status from Twilio status callback payload.
        Expected keys: SmsSid/MessageSid and SmsStatus/MessageStatus.
        """
        sid = data.get('SmsSid') or data.get('MessageSid')
        status = data.get('SmsStatus') or data.get('MessageStatus')
        if not sid:
            logger.warning('Message status callback without SID: %s', data)
            return True
        try:
            message = self.env['connect.message'].search([('message_sid', '=', sid)], limit=1)
            if not message:
                logger.info('Message not found for SID %s', sid)
                return True
            vals = {'status': status} if status else {}
            if (status or '').lower() == 'failed':
                # Some callbacks include error details
                code = data.get('ErrorCode')
                msg = data.get('ErrorMessage')
                if code:
                    vals['error_code'] = code
                if msg:
                    vals['error_message'] = msg
                    vals['has_error'] = True
            if vals:
                message.write(vals)
                self.env['connect.settings'].connect_reload_view('connect.message')
        except Exception as e:
            logger.warning('Failed to update message status for %s: %s', sid, e)
        return True
