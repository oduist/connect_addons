# -*- coding: utf-8 -*-

import json
import logging
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import format_connect_response, debug

logger = logging.getLogger(__name__)


class Number(models.Model):
    _name = 'connect.number'
    _description = 'Phone Number'
    _rec_name = 'phone_number'
    _order = 'phone_number'

    sid = fields.Char()
    is_ignored = fields.Boolean('Ignored')
    is_default = fields.Boolean(string='Default') # TODO: Remove after version 1.0
    phone_number = fields.Char(required=True)
    friendly_name = fields.Char()
    voice_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    voice_fallback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    voice_status_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    message_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    message_fallback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    twiml = fields.Many2one('connect.twiml', string='TwiML', ondelete='set null')
    destination = fields.Selection(selection=[
        ('user', 'User'),
        ('callflow', 'CallFlow'),
        ('twiml', 'TwiML'),
    ], ondelete='set null')
    callflow = fields.Many2one('connect.callflow', ondelete='set null')
    user = fields.Many2one('connect.user', ondelete='set null')

    _sql_constrains = [
        ('sid_unique', 'UNIQUE(sid)', 'This SID is already used!'),
        ('phone_number_unique', 'UNIQUE(phone_number)', 'This phone number is already used!'),
    ]

    def _get_twilio_urls(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        fallback_url = self.env['connect.settings'].get_param('api_fallback_url')
        edge = self.env['connect.settings'].get_param('twilio_edge')
        for rec in self:
            rec.voice_status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
            rec.voice_url = urljoin(api_url, 'twilio/webhook/number#e={}'.format(edge))
            if self.env['connect.settings'].get_param('twilio_region') == 'us1':
                # Messages are supported only in US region.
                rec.message_url = urljoin(api_url, 'twilio/webhook/message#e={}'.format(edge))
                rec.message_fallback_url = urljoin(api_url, 'twilio/webhook/message#e={}'.format(edge))
            else:
                rec.message_url = ''
                rec.message_fallback_url = ''
            if fallback_url:
                rec.voice_fallback_url = urljoin(fallback_url, 'twilio/webhook/number#e={}'.format(edge))
            else:
                rec.voice_fallback_url = ''

    def update_twilio_number(self, client):
        self.ensure_one()
        if self.is_ignored:
            debug(self, 'Ignoring number {} update.'.format(self.phone_number))
            return
        try:
            # Update phone number configuration
            number = client.incoming_phone_numbers(self.sid)
            number.update(
                friendly_name=self.friendly_name,
                voice_url=self.voice_url,
                voice_fallback_url=self.voice_fallback_url,
                sms_url=self.message_url,
                sms_fallback_url=self.message_fallback_url,
                status_callback=self.voice_status_url
            )
            debug(self, 'Number {} updated.'.format(self.phone_number))
        except Exception as e:
            logger.exception('Number Update Exception:')
            raise ValidationError(format_connect_response(str(e)))

    def write(self, vals):
        if 'destination' in vals:
            for field in ['user', 'callflow', 'twiml']:
                if field != vals['destination']:
                    vals.update({field: None})
        res = super().write(vals)
        # Check if twilio_auto_sync is disabled
        if not self.env["connect.settings"].get_param("twilio_auto_sync"):
            return res

        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not self.env.context.get('skip_twilio_sync'):
                rec.update_twilio_number(client)
        return res

    @api.model
    def sync(self):
        client = self.env['connect.settings'].get_client()
        region = self.env['connect.settings'].get_param('twilio_region')
        # We sync numbers Twilio -> Odoo.
        numbers = client.incoming_phone_numbers.list()
        for number in numbers:
            rec = self.search([('sid', '=', number.sid)])
            if not rec:
                # Create number in Odoo:
                rec = self.create({
                    'phone_number': number.phone_number,
                    'sid': number.sid,
                    'friendly_name': number.friendly_name,
                })
                # Update voice URLs and routing region.
                rec.update_twilio_number(client)
                self.env['connect.settings' ].connect_notify(
                    title="Twilio Sync",
                    message='Number {} added'.format(number.phone_number)
                )
            else:
                # Number already in Odoo, update Voice URLs and routing region
                rec.update_twilio_number(client)

        # Additionally, ensure all existing numbers have correct routing region
        if region:
            debug(self, 'Updating routing region to {} for all phone numbers during sync.'.format(region))
            all_numbers = self.search([('sid', '!=', False)])  # Only numbers with SID (not BYOC)
            for rec in all_numbers:
                try:
                    client.routes.v2.phone_numbers(rec.phone_number).update(voice_region=region)
                    debug(self, 'Updated routing region for number {} to {}.'.format(rec.phone_number, region))
                except Exception as e:
                    # Log warning but continue with other numbers
                    debug(self, 'Warning: Failed to update routing region for number {}: {}'.format(
                        rec.phone_number, str(e)), level="warning")

        # Remove numbers that exist only in Odoo (number was removed in Twilio).
        numbers_to_remove = self.search([
            ('sid', 'not in', [k.sid for k in numbers]),
            ('sid', '!=', False) # BYOC related number are not included!
        ])
        if numbers_to_remove:
            user_message = 'Number(s) {} removed in Twilio!'.format(
                ','.join([k.phone_number for k in numbers_to_remove]))
            numbers_to_remove.unlink()
            self.env['connect.settings' ].connect_notify(
                title="Twilio Sync",
                warning=True,
                sticky=True,
                message=user_message
            )

    def render(self, request={}, params={}):
        self.ensure_one()
        if not self.env["connect.license"].check_license('connect'):
            return "<Response><Pause length='1'/><Say>This is Oduist Connect. Your trial period is over. Please buy a license to continue.</Say><Pause length='1'/></Response>"
        if self.destination == 'twiml' and self.twiml:
            return self.twiml.render(request)
        elif self.destination == 'user' and self.user:
            return self.user.render(request)
        elif self.destination == 'callflow' and self.callflow:
            return self.callflow.render(request)
        else:
            return '<Response><Say>Number not configured. Goodbye!</Say></Response>'

    @api.model
    def route_call(self, request, params={}):
        debug(self, 'Route number call: %s' % json.dumps(request, indent=2))
        # Create call
        self.env['connect.call'].on_call_status(request)
        # Find the number
        number = self.sudo().search([('phone_number', '=', request['Called'])])
        if not number:
            return '<Response><Say>Number not found. Goodbye!</Say></Response>'
        return number.render(request=request, params=params)
