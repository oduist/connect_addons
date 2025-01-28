# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
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

    sid = fields.Char(required=True)
    is_ignored = fields.Boolean('Ignored')
    is_default = fields.Boolean(string='Default') # TODO: Remove after version 1.0
    phone_number = fields.Char(required=True, readonly=True)
    friendly_name = fields.Char()
    voice_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    voice_fallback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    voice_status_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    message_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    message_fallback_url = fields.Char(compute='_get_twilio_urls', compute_sudo=True)
    twiml = fields.Many2one('connect.twiml', string='TwiML', ondelete='set null')
    destination = fields.Selection(selection=[
        ('user', 'User'),
        ('queue', 'Queue'),
        ('callflow', 'CallFlow'),
        ('twiml', 'TwiML'),
    ])
    callflow = fields.Many2one('connect.callflow', ondelete='set null')
    user = fields.Many2one('connect.user', ondelete='set null')
    queue = fields.Many2one('connect.queue', ondelete='set null')

    _sql_constrains = [
        ('sid_unique', 'UNIQUE(sid)', 'This SID is already used!'),
        ('phone_number_unique', 'UNIQUE(phone_number)', 'This phone number is already used!'),
    ]

    def _get_twilio_urls(self):
        instance_uid = self.env['connect.settings'].get_param('instance_uid')
        api_url = self.env['connect.settings'].get_param('api_url')
        fallback_url = self.env['connect.settings'].get_param('api_fallback_url')
        for rec in self:
            rec.voice_status_url = urljoin(api_url,
                'twilio/webhook/{}/callstatus'.format(instance_uid))
            rec.voice_url = urljoin(api_url,
                'twilio/webhook/{}/number'.format(instance_uid))
            rec.message_url = urljoin(api_url,
                'twilio/webhook/{}/message'.format(instance_uid))
            rec.message_fallback_url = urljoin(api_url,
                'twilio/webhook/{}/message'.format(instance_uid))
            if fallback_url:
                rec.voice_fallback_url = urljoin(fallback_url,
                    'twilio/webhook/{}/number'.format(instance_uid))
            else:
                rec.voice_fallback_url = ''

    def update_twilio_number(self, client):
        self.ensure_one()
        if self.is_ignored:
            debug(self, 'Ignoring number {} update.'.format(self.phone_number))
            return
        try:
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
            for field in ['user', 'queue', 'callflow', 'twiml']:
                if field != vals['destination']:
                    vals.update({field: None})
        res = super().write(vals)
        client = self.env['connect.settings'].get_client()
        for rec in self:
            rec.update_twilio_number(client)
        return res

    @api.model
    def sync(self):
        client = self.env['connect.settings'].get_client()
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
                # Update voice URLs.
                rec.update_twilio_number(client)
                self.env['connect.settings' ].connect_notify(
                    title="Twilio Sync",
                    message='Number {} added'.format(number.phone_number)
                )
            else:
                # Number already in Odoo, update Voice URLs
                rec.update_twilio_number(client)
        # Remove numbers that exist only in Odoo (number was removed in Twilio).
        numbers_to_remove = self.search([('sid', 'not in', [k.sid for k in numbers])])
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

    @api.model
    def route_call(self, request):
        # Check access only for Twilio Service agent.
        if not self.env.user.has_group('connect.group_connect_billing'):
            logger.error('Access to Twilio webhook is denied!')
            return '<Response><Say>Access to Twilio webhook is denied!</Say></Response>'
        # Check Twilio request
        if not self.env['connect.settings'].check_twilio_request(request):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        debug(self, 'Route number call: %s' % json.dumps(request, indent=2))
        # Create call
        self.env['connect.call'].sudo().on_call_status(request, skip_twilio_check=True)
        # Find the number
        number = self.search([('phone_number', '=', request['Called'])])
        if not number:
            return '<Response><Say>Number not found. Goodbye!</Say></Response>'
        if number.destination == 'twiml' and number.twiml:
            return number.twiml.render(request)
        elif number.destination == 'user' and number.user:
            return number.user.render(request)
        elif number.destination == 'callflow' and number.callflow:
            return number.callflow.render(request)
        elif number.destination == 'queue' and number.queue:
            return number.queue.render(request)
        else:
            return '<Response><Say>Number not configured. Goodbye!</Say></Response>'
