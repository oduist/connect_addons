# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from markupsafe import Markup

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from .settings import debug

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
    callback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    status_callback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)

    # Properties
    messaging_limit = fields.Char(string='Messaging Limit', readonly=True)
    quality_rating = fields.Char(string='Quality Rating', readonly=True)

    # Voice application to use for WhatsApp voice calling integration
    voice_application = fields.Many2one('connect.twiml', string='Voice Application', ondelete='set null')

    # Local controls
    no_sync = fields.Boolean(string='Do not sync', default=False)
    is_default = fields.Boolean(string='Default WhatsApp Sender', help='Used as default when user has no personal sender set.')
    _sql_constraints = [
        ('sid_unique', 'UNIQUE(sid)', 'This Sender SID already exists!'),
        ('number_unique', 'UNIQUE(number)', 'This number already exists!'),
    ]

    @api.constrains('is_default')
    def _check_single_default(self):
        for rec in self:
            if rec.is_default:
                others = self.search([('is_default', '=', True), ('id', '!=', rec.id)], limit=1)
                if others:
                    raise ValidationError('Only one WhatsApp sender can be marked as default.')

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
            rec.callback_url = urljoin(api_url, f'twilio/webhook/message#e={edge}')
            rec.status_callback_url = urljoin(api_url, f'twilio/webhook/message_status#e={edge}')

    @api.model
    def sync(self):
        settings = self.env['connect.settings']
        account_sid = settings.get_param('account_sid')
        auth_token = settings.get_param('auth_token')
        if not account_sid or not auth_token:
            raise ValidationError('Twilio credentials are not configured.')
        # Skip Whatsapp Senders for non US regions.
        if settings.get_param('twilio_region') != 'us1':
            debug(self, 'Skipping WhatsApp Sender sync for not us1 region.')
            return
        url = 'https://messaging.twilio.com/v2/Channels/Senders'
        try:
            resp = requests.get(url, params={'Channel': 'whatsapp'}, auth=(account_sid, auth_token), timeout=30)
            if resp.status_code >= 400:
                raise ValidationError(f"Twilio error: {resp.status_code} {resp.text}")
            data = resp.json()
            debug(self, 'Whatsapp senders data: {}'.format(json.dumps(data, indent=2)))
            items = data.get('senders', [])
            twilio_sids = set()
            for item in items:
                if item.get('sid'):
                    twilio_sids.add(item.get('sid'))
                vals = self._prepare_vals_from_api(item)
                # Set default voice_application if not already set
                if 'voice_application' not in vals or not vals.get('voice_application'):
                    domain_app = self.env['connect.domain'].get_domain_app()
                    if domain_app:
                        vals['voice_application'] = domain_app.id
                # Upsert by sid if present, else by number
                rec = self.search([('sid', '=', vals.get('sid'))]) if vals.get('sid') else self.browse()
                if not rec and vals.get('number'):
                    rec = self.search([('number', '=', vals['number'])])
                if rec:
                    # Respect local no_sync flag: skip updating this record from Twilio
                    if rec.no_sync:
                        continue
                    rec.write(vals)
                    debug(self, 'Updated a Whatsapp sender {}'.format(rec.number))
                else:
                    rec = self.create([vals])[0]
                    debug(self, 'Created a Whatsapp sender {}'.format(rec.number))
                # Update sender webhook endpoints in Twilio
                try:
                    sid = rec.sid or item.get('sid')
                    if sid:
                        debug(self, 'Update Whatsapp Sender Webhook in Twilio for sid {}'.format(sid))
                        update_url = f'https://messaging.twilio.com/v2/Channels/Senders/{sid}'
                        payload = {
                            'webhook': {
                                'callback_method': 'POST',
                                'callback_url': rec.callback_url,
                                'status_callback_method': 'POST',
                                'status_callback_url': rec.status_callback_url,
                            }
                        }
                        # Pass voice_application_sid when configured
                        if rec.voice_application and rec.voice_application.sid:
                            payload['configuration'] = {
                                'voice_application_sid': rec.voice_application.sid
                            }
                        resp_u = requests.post(update_url, auth=(account_sid, auth_token), json=payload, timeout=30)
                        if resp_u.status_code >= 400:
                            debug(self, 'Failed to update sender: {}: {} {}'.format(sid, resp_u.status_code, resp_u.text))
                            logger.warning('Failed to update sender %s: %s %s', sid, resp_u.status_code, resp_u.text)
                        else:
                            debug(self, 'Sender webhook updated.')
                    else:
                        debug(self, 'Cannot update Twilio Webhooks, no sid for Sender ID {}'.format(rec.id))
                except Exception as e:
                    logger.exception('Sender webhook update error: %s', e)
            # Remove local senders missing in Twilio (by sid)
            if twilio_sids:
                missing = self.search([('sid', '!=', False), ('sid', 'not in', list(twilio_sids))])
                if missing:
                    debug(self, 'Removing missing Whatsapp Senders: {}'.format(', '.join(
                        [k.number for k in missing])))
                    missing.unlink()
            settings.connect_notify('WhatsApp Senders synced')
        except Exception as e:
            raise ValidationError("Failed to sync WhatsApp Senders: {}".format(e))

    def action_sync(self):
        self.sync()
        return True

    @api.model
    def get_default_sender(self, user=None):
        """Return the default WhatsApp sender.
        Preference order:
        - Given user's connect_user.whatsapp_sender_id
        - Current env user's connect_user.whatsapp_sender_id
        - Sender with is_default = True
        - Any available sender
        """
        connect_user = False
        try:
            if user and getattr(user, '_name', '') == 'connect.user':
                connect_user = user
            elif user and getattr(user, '_name', '') == 'res.users':
                connect_user = user.connect_user
            else:
                connect_user = self.env.user.connect_user
        except Exception:
            connect_user = False
        # 1) User preference
        if connect_user and connect_user.whatsapp_sender_id:
            return connect_user.whatsapp_sender_id
        # 2) Default flag
        default = self.search([('is_default', '=', True)], limit=1)
        if default:
            return default
        # 3) Any
        any_sender = self.search([], limit=1)
        return any_sender

    def send_whatsapp(self, recipient, body, res_model=None, res_id=None, raise_on_error=True, content_sid=None, content_variables=None):
        """Send a WhatsApp message using this sender and create connect.message + chatter.

        Args:
            recipient (str): E.164 phone (e.g., +123456789).
            body (str): Message text.
            res_model (str): Optional model to post to chatter.
            res_id (int): Optional record id to post to chatter.
            raise_on_error (bool): When True raise ValidationError on failures, otherwise log and return False.
            content_sid (str): Optional Twilio Content SID for using message templates.
            content_variables (str): Optional JSON string of template variables.
        Returns:
            connect.message record or False on error when raise_on_error=False
        """
        self.ensure_one()
        if not self.number:
            raise ValidationError('WhatsApp sender has no number configured.')
        # Check 24-hour window for WhatsApp - only if not using a content template
        if not content_sid:
            # Find last incoming WhatsApp message from this recipient
            last_incoming = self.env['connect.message'].sudo().search([
                ('message_type', '=', 'WhatsApp'),
                ('from_number', '=', recipient),
                ('direction', '=', 'incoming')
            ], order='create_date desc', limit=1)

            if last_incoming:
                # Check if message is older than 24 hours
                time_diff = datetime.now() - last_incoming.create_date
                if time_diff > timedelta(hours=24):
                    raise ValidationError(
                        '24 hours contact window has been expired. '
                        'Please select a message template to initiate a new contact window.'
                    )
                debug(self, 'Last incoming message received less then 24 hours ago, we can send a message.')
            else:
                # No previous incoming message found - must use template
                debug(self, 'No last incoming 24 hours ago message found, refuse to send, use a template')
                raise ValidationError(
                    '24 hours contact window has been expired. '
                    'Please select a message template to initiate a new contact window.'
                )
        client = self.env['connect.settings'].get_client()
        try:
            create_kwargs = {
                'to': f'whatsapp:{recipient}',
                'from_': f'whatsapp:{self.number}',
            }
            if content_sid:
                create_kwargs['content_sid'] = content_sid
                if content_variables:
                    create_kwargs['content_variables'] = content_variables
                # Do not send body when using content templates
                create_kwargs['body'] = body or ''
            else:
                create_kwargs['body'] = body or ''
            message = client.messages.create(**create_kwargs)
        except Exception as e:
            if raise_on_error:
                raise ValidationError('Unable to send WhatsApp message. Please check the number and sender configuration.')
            logger.error('Unable to send WhatsApp message to %s via %s: %s', recipient, self.number, e)
            return False
        if not message:
            if raise_on_error:
                raise ValidationError('WhatsApp API did not return a message SID.')
            logger.error('WhatsApp API did not return a message SID for recipient %s', recipient)
            return False

        # Create connect.message record mirroring ConnectMessage.send
        sender_user = self.env.user
        partner = self.env['res.partner'].get_partner_by_number(recipient)
        msg_vals = {
            'message_type': 'WhatsApp',
            'to_number': recipient,
            'from_number': self.number,
            'body': body,
            'sender_user': sender_user.id,
            'partner': partner.id if partner else False,
            'res_model': res_model,
            'res_id': res_id,
            'status': 'sent',
            'account_sid': getattr(message, 'account_sid', False),
            'messaging_service_sid': getattr(message, 'messaging_service_sid', False),
            'num_media': getattr(message, 'num_media', 0) or 0,
            'error_code': getattr(message, 'error_code', False),
            'error_message': getattr(message, 'error_message', False),
            'message_sid': message.sid,
        }
        msg = self.env['connect.message'].sudo().create(msg_vals)

        # Post to chatter if relevant
        if res_model and res_id:
            chatter_message = Markup(f"<div class='d-flex flex-row'>"
                                     f"<p class='px-1'>{body}</p></div>")
            self.chatter_post(res_model, res_id, self.env.user.partner_id.id, chatter_message)
        return msg

    def chatter_post(self, res_model, res_id, author, body):
        try:
            mt_note = self.env.ref('mail.mt_note').id
            obj = self.env[res_model].browse(res_id)
            if hasattr(obj, 'message_post'):
                chatter = obj.sudo().with_context(mail_create_nosubscribe=True).message_post(
                    body=body,
                    subtype_id=mt_note,
                    message_type='WhatsApp',
                    author_id=author,
                )
                self.env['mail.notification'].sudo().create([{
                    'author_id': chatter.author_id.id,
                    'mail_message_id': chatter.id,
                    'res_partner_id': chatter.author_id.id,
                    'sms_number': self.number,
                    'notification_type': 'WhatsApp',
                    'is_read': True,
                    'notification_status': 'ready',
                }])
                self.env['connect.settings'].connect_reload_view(res_model)
        except Exception as e:
            logger.warning('Failed to post WhatsApp chatter message on %s,%s: %s', res_model, res_id, e)

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
            connect_user = self.env.ref("connect.user_connect_webhook")
            connect_partner = connect_user.partner_id
            if (status or '').lower() == 'failed':
                # Some callbacks include error details
                code = data.get('ErrorCode')
                msg = data.get('ErrorMessage')
                if code:
                    vals['error_code'] = code
                if msg:
                    vals['error_message'] = msg
                    vals['has_error'] = True
                if message.res_model and message.res_id:
                    chatter_message = 'Failed to send this Whatsapp message'
                    self.chatter_post(message.res_model, message.res_id, connect_partner.id, chatter_message)
            elif (status or '').lower() == 'read' and message.res_model and message.res_id:
                chatter_message = 'Whatsapp message is read.'
                self.chatter_post(message.res_model, message.res_id, connect_partner.id, chatter_message)
            elif (status or '').lower() ==  'undelivered' and message.res_model and message.res_id:
                chatter_message = ('24 hours contact window has been expired. '
                        'Please select a message template to initiate a new contact window!')
                self.chatter_post(message.res_model, message.res_id, connect_partner.id, chatter_message)
            if vals:
                message.write(vals)
                self.env['connect.settings'].connect_reload_view('connect.message')
        except Exception as e:
            logger.warning('Failed to update message status for %s: %s', sid, e)
        return True
