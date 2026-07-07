# -*- coding: utf-8 -*-
"""
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist

This file contains license validation logic.
Modification is prohibited under Oduist Proprietary License.
See LICENSE and COPYRIGHT files for full terms.
"""

import json
import logging
from urllib.parse import urljoin
from odoo import fields, models, api, release
if release.version_info[0] >= 19:
    from odoo.models import Constraint
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
    # NOTE: no `ondelete=` here. On a Selection, `ondelete` must be a dict
    # keyed by the values contributed via `selection_add` (submodules), not a
    # bare string. A string crashes _process_ondelete ('str' has no .get) when
    # a submodule value is later removed — e.g. dropping 'elevenlabs_agent'.
    # Removed values are handled explicitly by the connect_elevenlabs migration.
    destination = fields.Selection(selection=[
        ('user', 'User'),
        ('callflow', 'CallFlow'),
        ('twiml', 'TwiML'),
        ('sip_trunk', 'SIP Trunk'),
    ])
    callflow = fields.Many2one('connect.callflow', ondelete='set null')
    user = fields.Many2one('connect.user', ondelete='set null')
    sip_trunk = fields.Many2one(
        'connect.sip_trunk', string='SIP Trunk', ondelete='set null',
        help='Twilio Elastic SIP Trunk this number is attached to.')

    # Use modern constraint syntax for Odoo 19, fallback to legacy for older versions
    if release.version_info[0] >= 19:
        _sid_unique = Constraint('UNIQUE(sid)', 'This SID is already used!')
        _phone_number_unique = Constraint('UNIQUE(phone_number)', 'This phone number is already used!')
    else:
        _sql_constraints = [
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
            # Messages are supported only in US region and don't use edges.
            rec.message_url = urljoin(api_url, 'twilio/webhook/message')
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
        if self.destination == 'sip_trunk' and self.sip_trunk:
            debug(self, 'Skipping voice_url update for trunk-attached number {}.'.format(
                self.phone_number))
            return
        try:
            number = client.incoming_phone_numbers(self.sid)
            number.update(
                friendly_name=self.friendly_name,
                voice_url=self.voice_url,
                voice_fallback_url=self.voice_fallback_url,
                status_callback=self.voice_status_url
            )
            region = self.env['connect.settings'].sudo().get_param('twilio_region')
            if region and region != 'us1':
                us_client = self.env['connect.settings'].get_client(region=False)
                us_client.incoming_phone_numbers(self.sid).update(
                    sms_url=self.message_url,
                    sms_fallback_url=self.message_fallback_url,
                )
            else:
                number.update(
                    sms_url=self.message_url,
                    sms_fallback_url=self.message_fallback_url,
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
        # Snapshot previous (trunk, destination) — both can flip the desired
        # Twilio binding state (see _sync_sip_trunk_membership).
        binding_affected = 'sip_trunk' in vals or 'destination' in vals
        prev_state = {
            rec.id: (rec.sip_trunk, rec.destination)
            for rec in self
        } if binding_affected else {}
        res = super().write(vals)
        # Check if twilio_auto_sync is disabled
        if not self.env["connect.settings"].get_param("twilio_auto_sync"):
            return res

        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not self.env.context.get('skip_twilio_sync'):
                rec.update_twilio_number(client)
                if rec.id in prev_state:
                    prev_trunk, prev_dest = prev_state[rec.id]
                    rec._sync_sip_trunk_membership(client, prev_trunk, prev_dest)
        return res

    def _sync_sip_trunk_membership(self, client, previous_trunk, previous_destination):
        """Attach/detach this number on the Twilio Elastic SIP Trunk.

        When destination='sip_trunk' the number is natively attached to
        the trunk and Twilio forwards inbound calls directly to the
        trunk's Origination URLs. The number's voice_url is bypassed
        in that state, so Odoo-side call logging via webhook does not
        fire — that is by design; the receiving PBX is the call-record
        source.
        """
        self.ensure_one()
        if not self.sid:
            return
        want_trunk = (self.sip_trunk
                      if self.destination == 'sip_trunk' and self.sip_trunk
                      else self.env['connect.sip_trunk'])
        was_trunk = (previous_trunk
                     if previous_destination == 'sip_trunk' and previous_trunk
                     else self.env['connect.sip_trunk'])
        if was_trunk and was_trunk != want_trunk and was_trunk.sid:
            try:
                client.trunking.v1.trunks(
                    was_trunk.sid).phone_numbers(self.sid).delete()
            except Exception as e:
                if 'not found' not in str(e).lower():
                    logger.warning('Detach number %s from trunk %s: %s',
                                   self.phone_number, was_trunk.sid, e)
        if want_trunk and want_trunk != was_trunk and want_trunk.sid:
            try:
                client.trunking.v1.trunks(
                    want_trunk.sid).phone_numbers.create(
                        phone_number_sid=self.sid)
            except Exception as e:
                if 'already' not in str(e).lower():
                    logger.warning('Attach number %s to trunk %s: %s',
                                   self.phone_number, want_trunk.sid, e)

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
            all_numbers = self.search([('sid', '!=', False), ('is_ignored', '=', False)])  # Only numbers with SID (not BYOC), skip ignored
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
        if not self.env["oduist.license"].check_license('connect'):
            return "<Response><Pause length='1'/><Say>This is Oduist Connect. Your trial period is over. Please buy a license to continue.</Say><Pause length='1'/></Response>"
        if self.destination == 'twiml' and self.twiml:
            return self.twiml.render(request)
        elif self.destination == 'user' and self.user:
            return self.user.render(request)
        elif self.destination == 'callflow' and self.callflow:
            return self.callflow.render(request)
        elif self.destination == 'sip_trunk':
            return ('<Response><Say>Number routed natively via SIP '
                    'Trunk.</Say></Response>')
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
