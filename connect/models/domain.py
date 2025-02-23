# -*- coding: utf-8 -*-

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from .settings import format_connect_response, debug
from .twiml import pretty_xml


logger = logging.getLogger(__name__)


class Domain(models.Model):
    _name = 'connect.domain'
    _rec_name = 'friendly_name'
    _description = 'Twilio Domain'
    _order = 'friendly_name'

    sid = fields.Char('SID', readonly=True)
    application = fields.Many2one('connect.twiml', ondelete='restrict', required=True,
                                  default=lambda self: self.get_domain_app())
    cred_list_sid = fields.Char('Cred List SID', readonly=True)
    subdomain = fields.Char(required=True)
    domain_name = fields.Char(compute='_get_domain_name', inverse='_set_domain_name')
    friendly_name = fields.Char(required=True)
    sip_registration = fields.Boolean('SIP Registration', readonly=True, default=True)
    delete_protection = fields.Boolean(default=True)

    _sql_constrains = [
        ('uniq_subdomain', 'UNIQUE(subdomain)', 'This subdomain is already used!')
    ]

    def _get_domain_name(self):
        for rec in self:
            rec.domain_name = rec.subdomain + '.' + 'sip.twilio.com'

    def _set_domain_name(self):
        for rec in self:
            rec.subdomain = rec.domain_name.split('.')[0]

    def get_domain_app(self):
        # Domain must be created.
        app = self.env['connect.twiml'].search(
            [('code_type', '=', 'model_method'),
             ('model', '=', 'connect.domain'),
             ('method', '=', 'route_call')], limit=1)
        if not app:
            # Who removed that!?
            app = self.env['connect.twiml'].create({
                'model': 'connect.domain',
                'method': 'route_call',
                'code_type': 'model_method',
                'name': 'SIP Domains calls',
                'description': 'Required application!'
            })
        return app

    def create_twilio_sip_domain(self, client):
        self.ensure_one()
        domain = client.sip.domains.create(
            friendly_name=self.friendly_name,
            domain_name=self.domain_name,
            voice_url=self.application.voice_url,
            voice_fallback_url=self.application.voice_fallback_url,
            sip_registration=True,
            voice_status_callback_url=self.application.voice_status_url)
        # Create cred lists for domain.
        credential_list = client.sip.credential_lists.create(
            friendly_name=domain.sid)
        # Assotiate cred list with REGISTER.
        auth_registrations_credential_list_mapping = client.sip \
            .domains(domain.sid).auth.registrations.credential_list_mappings.create(
                credential_list_sid=credential_list.sid)
        # Assotiate cred list with INVITE.
        auth_registrations_credential_list_mapping = client.sip \
            .domains(domain.sid).auth.calls.credential_list_mappings.create(
                credential_list_sid=credential_list.sid)
        self.write({
            'sid': domain.sid,
            'cred_list_sid': credential_list.sid,
        })
        debug(self, 'Domain {} was created'.format(self.friendly_name))
        return domain


    def create_domain(self, client):
        self.ensure_one()
        try:
            # Create app first if requeired.
            self.application = self.get_domain_app()
            # Create domain.
            self.create_twilio_sip_domain(client)
        except Exception as e:
            if 'already exists' in str(e):
                    raise ValidationError('This domain name already exists in Twilio!')
            else:
                ret = format_connect_response(e)
                raise ValidationError(ret)

    @api.model_create_multi
    def create(self, vals_list):
        rec = super().create(vals_list)
        client = self.env['connect.settings'].get_client()
        if not self.env.context.get('no_twilio_create'):
            rec.create_domain(client)
        return rec

    def unlink(self):
        for rec in self:
            if rec.delete_protection:
                raise ValidationError('Remove delete protection to delete the domain!')
        client = self.env['connect.settings'].get_client()
        for rec in self:
            try:
                # Remove creds
                client.sip.domains(rec.sid).auth.registrations.credential_list_mappings(
                    rec.cred_list_sid).delete()
                client.sip.domains(rec.sid).auth.calls.credential_list_mappings(
                    rec.cred_list_sid).delete()
                debug(self, 'Credential_list_mappings removed.')
                client.sip.credential_lists(rec.cred_list_sid).delete()
                debug(self, 'Credential_list removed.')
                # Remove domain
                client.sip.domains(rec.sid).delete()
                debug(self, 'Domain removed.')
            except Exception as e:
                if 'not found' in str(e):
                    # Domain was removed from Twilio, remove here.
                    pass
                else:
                    raise ValidationError(format_connect_response(e))
        return super().unlink()

    def update_twilio_domain(self, client):
        self.ensure_one()
        try:
            domain = client.sip.domains(self.sid)
            domain.update(
                friendly_name=self.friendly_name,
                domain_name=self.domain_name,
                voice_url=self.application.voice_url,
                voice_fallback_url=self.application.voice_fallback_url,
                voice_status_callback_url=self.application.voice_status_url)
            debug(self, 'Domain {} updated'.format(self.friendly_name))
        except Exception as e:
            if 'was not found' in str(e):
                logger.warning('Twilio domain %s not found, creating.', self.friendly_name)
                self.create_domain(client)
            elif 'already exists' in str(e):
                raise ValidationError('This domain name already used in Twilio!')
            else:
                raise

    def write(self, vals):
        client = self.env['connect.settings'].get_client()
        # Update only Twilio fields.
        if not (set(['friendly_name', 'domain_name', 'subdomain', 'app']) & set(vals.keys())):
            return super().write(vals)
        res = super().write(vals)
        # Iterate over records and update twilio.
        try:
            for rec in self:
                rec.update_twilio_domain(client)
        except Exception as e:
            raise ValidationError(format_connect_response(e))

    @api.model
    def sync(self):
        client = self.env['connect.settings'].get_client()
        # Twilio records
        twilio_records = client.sip.domains.list()
        twilio_sids = set([k.sid for k in twilio_records])
        # Odoo records
        odoo_sids = set(self.search([]).mapped('sid'))
        # Sets
        only_in_twilio = twilio_sids - odoo_sids
        debug(self, 'Only in Twilio domain SIDs: {}'.format(only_in_twilio))
        only_in_odoo = odoo_sids - twilio_sids
        debug(self, 'Only in Odoo domain SIDs: {}'.format(only_in_odoo))
        common_recs = odoo_sids & twilio_sids
        debug(self, 'Common domain SIDs: {}'.format(common_recs))
        # Create in Odoo what is in only in Twilio
        for sid in only_in_twilio:
            domain = client.sip.domains(sid).fetch()
            credential_list_mappings = client.sip \
                .domains(sid).auth.registrations.credential_list_mappings.list()
            if len(credential_list_mappings) > 1:
                logger.warning('SIP Domain %s has more credential list. This is not supported.')
                raise ValidationError('Can only import Twilio domains with one credential list!')
            elif len(credential_list_mappings) == 1:
                credential_list_sid = credential_list_mappings[0].sid
                odoo_domain = self.with_context(no_twilio_create=True).create({
                    'sid': domain.sid,
                    'friendly_name': domain.friendly_name,
                    'subdomain': domain.domain_name.split('.')[0],
                    'sip_registration': True,
                    'cred_list_sid': credential_list_sid,
                })
                odoo_domain.application = self.get_domain_app()
                # Push back voice urls.
                odoo_domain.update_twilio_domain(client)
                # Create SIP users
                creds = client.sip.credential_lists(credential_list_sid).credentials.list()
                for cred in creds:
                    self.env['connect.user'].with_context(no_twilio_create=True).create({
                        'sid': cred.sid,
                        'username': cred.username,
                        'sip_enabled': True
                    })
                    debug(self, 'Created Odoo SIP username {}'.format(cred.username))
            else:
                credential_list = client.sip.credential_lists.create(
                    friendly_name=domain.sid)
                debug(self, 'Credential list for domain {} created.'.format(domain.domain_name))
                # Assotiate cred list with REGISTER.
                auth_registrations_credential_list_mapping = client.sip \
                    .domains(domain.sid).auth.registrations.credential_list_mappings.create(
                        credential_list_sid=credential_list.sid)
                # Assotiate cred list with INVITE.
                auth_registrations_credential_list_mapping = client.sip \
                    .domains(domain.sid).auth.calls.credential_list_mappings.create(
                        credential_list_sid=credential_list.sid)
                odoo_domain = self.with_context(no_twilio_create=True).create({
                    'sid': domain.sid,
                    'cred_list_sid': credential_list.sid,
                    'friendly_name': domain.friendly_name,
                    'subdomain': domain.domain_name.split('.')[0],
                    'sip_registration': True,
                })
                odoo_domain.application = self.get_domain_app()
                # Push back voice urls.
                odoo_domain.update_twilio_domain(client)
        # Create in Twilio what is only in Odoo.
        for sid in only_in_odoo:
            odoo_domain = self.search([('sid','=', sid)])
            odoo_domain.create_twilio_domain(client)
        # Update what exists in both.
        for sid in common_recs:
            odoo_domain = self.search([('sid', '=', sid)])
            odoo_domain.update_twilio_domain(client)

    @api.model
    def route_call(self, request, params={}):
        debug(self, 'Domain call to %s' % request.get('To'))
        # Create call
        self.env['connect.call'].on_call_status(request)
        # Check if it is a SIP call and extract To from it.
        found = re.search(r'^sip:(.+)@(.+)\.sip\.((.+)\.)?twilio\.com', request.get('To'))
        if found:
            found_num = found.group(1)
        else:
            found_num = request.get('To')
        exten = self.env['connect.exten'].sudo().search([('number', '=', found_num)])
        if not exten:
            # Get all extensions and match by pattern.
            # TODO: Handle bad exten numbers like 70[ that cannot be used by re.match.
            all_extensions = self.env['connect.exten'].sudo().search([])
            # Handle case of extension number is defined as E1.64 (with +).
            matching_extensions = all_extensions.filtered(
                lambda x: re.match(r'^{}$'.format(
                    '\\'+ x.number if x.number.startswith('+') else x.number), found_num))
            if len(matching_extensions) > 1:
                logger.error('Multiple extensions %s found for number %s', matching_extensions, found_num)
                return '<Response><Say>Multiple extensions found. Check your dialplan. Goodbye! </Say></Response>'
            elif len(matching_extensions) == 1:
                exten = matching_extensions[0]
        if exten:
            # Render extensions dialplan
            res = exten.render(request=request, params=params)
            return res
        elif isinstance(found_num, str) and found_num.startswith('+'):
            return self.originate_external_call(found_num, request, params=params)
        else:
            return '<Response><Say>Extension not found. Goodbye! </Say></Response>'

    def originate_external_call(self, number, request, params={}):
        debug(self, 'Outgoing call to %s' % number)
        # Find outgoing rules.
        rule = self.env['connect.outgoing_rule'].find_rule(number)
        if not rule:
            return '<Response><Say>No outgoing rule found for this destination! Goodbye!</Say></Response>'
        default_number = self.env['connect.outgoing_callerid'].search([('is_default', '=', True)], limit=1)
        # Find the user by caller.
        user = self.env['connect.user'].get_user_by_uri(request.get('From'))
        if user.outgoing_callerid:
            callerId = user.outgoing_callerid.number
        else:
            callerId = default_number.number
        if not callerId:
            return '<Response><Say>You must select a default number for caller ID!</Say></Response>'
        response = VoiceResponse()
        api_url = self.env['connect.settings'].get_param('api_url')
        status_url = urljoin(api_url, 'twilio/webhook/callstatus')
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus')
        if user.record_calls:
            dial = Dial(timeout=60,
                        callerId=callerId,
                        record='record-from-answer',
                        recordingStatusCallback=record_status_url,
            )
        else:
            dial = Dial(timeout=60, callerId=callerId)
        if rule.byoc:
            dial.number(number, byoc=rule.byoc.sid, statusCallback=status_url, statusCallbackEvent='initiated answered completed')
        else:
            dial.number(number, statusCallback=status_url, statusCallbackEvent='initiated answered completed')
        response.append(dial)
        debug(self, 'Originate external: %s' % pretty_xml(str(response)))
        return response
