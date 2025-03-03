# -*- coding: utf-8 -*-

import json
import jinja2
import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from .settings import format_connect_response, debug
from .twiml import pretty_xml

logger = logging.getLogger(__name__)


class User(models.Model):
    _name = 'connect.user'
    _rec_name = 'username'
    _description = 'Twilio User'
    _order = 'username'

    sid = fields.Char('SID', readonly=True)
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number', store=True)
    sip_enabled = fields.Boolean('SIP Phone Enabled')
    client_enabled = fields.Boolean('Web Phone Enabled', default=True)
    name = fields.Char(compute='_get_name')
    user = fields.Many2one('res.users', string='Odoo User', domain=[('share', '=', False)])
    domain = fields.Many2one('connect.domain', required=True, ondelete='cascade',
                            default=lambda x: x.env['connect.domain'].search([], limit=1))
    username = fields.Char(required=True)
    password = fields.Char(groups="connect.group_connect_admin,connect.group_connect_user")
    uri = fields.Char('SIP URI', compute='_get_sip_uri', store=True)
    record_calls = fields.Boolean()
    voicemail_enabled = fields.Boolean()
    voicemail_prompt = fields.Text(default="Hello, this is {{user.name}}. I'm unable to take your call right now. Please leave a message after the tone.")
    application = fields.Many2one('connect.twiml')
    ring_first = fields.Selection(selection=[('sip', 'SIP'),('client', 'Client')],
                                  required=True, default='client')
    ring_second = fields.Selection(selection=[('sip', 'SIP'),('client', 'Client')],
                                  required=False, default='sip')
    sip_ring_timeout = fields.Integer(required=True, default=30, string='SIP ring timeout')
    client_ring_timeout = fields.Integer(required=True, default=10, string='Web client ring timeout')
    callerid_number = fields.Many2one('connect.number', ondelete='restrict') # TODO: Remove after 1.0
    outgoing_callerid = fields.Many2one('connect.outgoing_callerid', ondelete='set null',
        domain=['|',('status', '=', 'validated'),('callerid_type', '=', 'number')])
    missed_calls_notify = fields.Boolean(default=False, help='Notify user on missed calls.')

    _sql_constraints = [
        ('user_uniq', 'UNIQUE("user")', 'This Odoo user account is already defined!'),
        ('username_uniq', 'UNIQUE(username)', 'This PBX username is already defined!'),
    ]

    @api.depends('username', 'domain', 'domain.domain_name', 'domain.subdomain')
    def _get_sip_uri(self):
        for rec in self:
            rec.uri = '{}@{}'.format(rec.username, rec.domain.domain_name)

    def _create_sip_account(self, username, password, client=None):
        self.ensure_one()
        try:
            client = client or self.env['connect.settings'].get_client()
            credential = client.sip.credential_lists(
                self.domain.cred_list_sid).credentials.create(
                    username=username, password=password)
            if not credential:
                raise ValidationError('Cannot create a SIP user!')
            return credential.sid
        except Exception as e:
            if 'A strong password is required' in str(e):
                msg = 'A strong password is required. It must have a minimum length of 12, at least one number, uppercase char and lowercase character.'
                raise ValidationError(msg)
            else:
                raise ValidationError(format_connect_response(e))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('no_twilio_create'):
            for rec in recs:
                try:
                    if rec.sip_enabled and rec.password:
                        if not self.env.context.get('skip_create_credential'):
                            rec.sid = rec._create_sip_account(username=rec.username, password=rec.password)
                        # Don't keep SIP password in Odoo.
                        rec.with_context(skip_sync=True).password = '*' * len(rec.password)
                except Exception as e:
                    if 'A strong password is required' in str(e):
                        msg = 'A strong password is required. It must have a minimum length of 12, at least one number, uppercase char and lowercase character.'
                        raise ValidationError(msg)
                    else:
                        raise ValidationError(format_connect_response(e))
        if recs and not self.env.context.get('no_clear_cache'):
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return recs

    def delete_sip_account(self):
        self.ensure_one()
        if not self.sid:
            logger.warning(
                'Attempt to delete SIP account %s (%s) without SID!', self.id, self.name)
            return
        try:
            client = self.env['connect.settings'].get_client()
            credential = client.sip.credential_lists(
                self.domain.cred_list_sid).credentials(self.sid).delete()
            debug(self, 'Deleted SIP account {}.'.format(self.username))
            return True
        except Exception as e:
            if 'not found' in str(e):
                logger.warning('SIP account %s was not present in Twilio.', self.username)
            else:
                raise ValidationError(format_connect_response(e))

    def unlink(self):
        for rec in self:
            rec.delete_sip_account()
        res = super().unlink()
        if res and not self.env.context.get('no_clear_cache'):
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res

    def _update_sip_password(self, password):
        self.ensure_one()
        if not self.sid:
            logger.warning('SIP account %s SID not set, not updating.', self.id)
            return
        try:
            client = self.env['connect.settings'].get_client()
            credential = client.sip.credential_lists(
                self.domain.cred_list_sid).credentials(self.sid).update(password=password)
        except Exception as e:
            if 'A strong password is required.' in str(e):
                msg = 'A strong password is required. It must have a minimum length of 12, at least one number, uppercase char and lowercase character.'
                raise ValidationError(msg)
            elif 'not found' in str(e):
                # Twilio user is not present, create it.
                self._create_sip_account(self.username, password)
            else:
                raise ValidationError(format_connect_response(e))

    def write(self, vals):
        if self.env.context.get('skip_sync'):
            return super().write(vals)
        if 'username' in vals:
            raise ValidationError('Username cannot be changed!')
        for rec in self:
            if vals.get('sip_enabled') is False and rec.sid:
                rec.delete_sip_account()
                vals['sid'] = False
                vals['password'] = False
            if vals.get('password'):
                if rec.sid:
                    rec._update_sip_password(vals['password'])
                else:
                    # SIP was enabled, create SIP user account.
                    vals['sid'] = self._create_sip_account(rec.username, vals['password'])
                # Don't keep SIP password in Odoo.
                vals['password'] = '*' * len(vals['password'])
        res = super().write(vals)
        if res and not self.env.context.get('no_clear_cache'):
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res

    def _get_name(self):
        for rec in self:
            rec.name = rec.user.name if rec.user else rec.username

    @api.constrains('username')
    def _check_username(self):
        for rec in self:
            if not rec.username.isalnum():
                raise ValidationError('Username must be alphanumeric!')

    def render(self, request={}, params={}):
        self.ensure_one()
        channel = self.env['connect.channel'].search([('sid', '=', request.get('CallSid'))])
        call = channel.call
        # Check callerid for client calls
        user = self.env['connect.user'].get_user_by_uri(request.get('From'))
        caller_name = params.get('CallerName', False)
        if user:
            callerId = user.exten.number or ''
            if not callerId:
                logger.warning('Exten not set for user %s', user.name)
            caller_name = user.name
        else:
            callerId = request.get('From')
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus')
        status_url = urljoin(api_url, 'twilio/webhook/callstatus')
        action_url = urljoin(
            api_url, 'twilio/webhook/connect.user/call_action/{}'.format(self.id)
        )
        response = VoiceResponse()
        dial_sip_kwargs = {'timeout': self.sip_ring_timeout, 'callerId': callerId, 'action': action_url}
        if self.record_calls:
            dial_sip_kwargs.update({
                'recordingStatusCallback': record_status_url,
                'record': 'record-from-answer-dual'
            })
        dial_sip = Dial(**dial_sip_kwargs)
        dial_sip.sip(
            'sip:{}'.format(self.uri),
            statusCallbackEvent='initiated answered completed',
            statusCallback=status_url)

        dial_client_kwargs = {'timeout': self.client_ring_timeout, 'callerId': callerId, 'action': action_url}
        if self.record_calls:
            dial_client_kwargs.update({
                'record': 'record-from-answer',
                'recordingStatusCallback': record_status_url
            })
        dial_client = Dial(**dial_client_kwargs)
        client = Client(
            statusCallbackEvent='initiated answered completed',
            statusCallback=status_url)
        client.identity(self.uri)
        client.parameter(name='CallerName', value=caller_name)
        if call and call.partner:
            partner_id = call.partner.id
        elif channel and channel.caller_user:
            partner_id = channel.caller_user.partner_id.id
        else:
            partner_id = False
        client.parameter(name='Partner', value=partner_id)
        dial_client.append(client)
        if self.ring_first == 'sip':
            response.append(dial_sip)
        elif self.ring_first == 'client':
            response.append(dial_client)
        if self.ring_second == 'sip':
            response.append(dial_sip)
        elif self.ring_second == 'client':
            response.append(dial_client)
        debug(self, pretty_xml(str(response)))
        return response

    @api.model
    def get_client_token(self):
        has_user_group = self.env.user.has_group('connect.group_connect_user')
        has_admin_group = self.env.user.has_group('connect.group_connect_admin')
        if not (has_user_group or has_admin_group):
            return False
        user = self.search([('user', '=', self.env.user.id)])
        if not user:
            return False
        if not user.client_enabled:
            return False
        account_sid = self.env['connect.settings'].sudo().get_param('account_sid')
        api_key = self.env['connect.settings'].sudo().get_param('twilio_api_key')
        api_secret = self.env['connect.settings'].sudo().get_param('twilio_api_secret')
        identity = user.uri
        token = AccessToken(account_sid, api_key, api_secret, identity=identity, ttl=3600)
        voice_grant = VoiceGrant(
            outgoing_application_sid=user.application.sid or user.domain.application.sid,
            outgoing_application_params={},
            incoming_allow=True,
        )
        token.add_grant(voice_grant)
        return token.to_jwt()

    @api.model
    def get_user_by_exten_number(self, search_query):
        # Called from Client.
        has_group = self.env.user.has_group
        if not any([has_group('connect.group_connect_user'), has_group('connect.group_connect_admin')]):
            raise ValidationError('Only Connect users can search other Connect users!')
        domain = [['exten_number', '=', search_query]]
        search_fields = ['id', 'name', 'exten_number', 'user']
        user = self.sudo().search_read(domain, search_fields, limit=1, order='exten_number asc')
        return user[0] if user else False

    @api.model
    # @tools.ormcache('userinfo') - psycopg2.InterfaceError: Cursor already closed
    def get_user_by_uri(self, userinfo):
        if not userinfo:
            # Return empty set.
            return self.env['connect.user']
        re_call_uri = re.compile(r'^(?:sip|client):([^\s@]+@[^\s;]+)(?:;[^&\s]+(?:&[^&\s]+)*)?')
        found_uri = re_call_uri.search(userinfo)
        if found_uri:
            user = self.env['connect.user'].search([
                ('uri', '=', found_uri.group(1))])
            debug(self, 'Found user: {} by {}.'.format(user.username, userinfo))
            return user
        # Return empty set.
        return self.env['connect.user']

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'user')

    @api.model
    def on_call_action(self, record_id, request):
        debug(self, 'Call action: {}'.format(json.dumps(request, indent=2)))
        response = VoiceResponse()
        user = self.browse(record_id)
        if request.get('RecordingSid'):
            response.hangup()
            return response
        if request.get('DialCallStatus') != 'completed':
            if user.voicemail_enabled:
                # The call voicemail
                api_url = self.env['connect.settings'].sudo().get_param('api_url')
                record_status_url = urljoin(api_url, 'twilio/webhook/vm_recordingstatus')
                user.get_voicemail_prompt(response)
                response.record(
                    maxLength=120,
                    finishOnKey='#',
                    playBeep=True,
                    recordingStatusCallback=record_status_url)
            else:
                response.hangup()
        else:
            response.hangup()
        debug(self, pretty_xml(str(response)))
        return response

    def get_voicemail_prompt(self, response):
        self.ensure_one()
        debug(self, 'Saying voicemail prompt {}'.format(self.name))
        voicemail_prompt = self.render_voicemail_prompt()
        response.say(voicemail_prompt)

    def render_voicemail_prompt(self):
        self.ensure_one()
        # Render user greeting.
        environment = jinja2.Environment()
        template = environment.from_string(self.voicemail_prompt)
        return template.render({'user': self})

    @api.onchange('domain')
    def _restrict_sip_domain_change(self):
        if self.sip_enabled and self.sid:
            raise ValidationError('You cannot change SIP domain for existing SIP account! Disable SIP account first!')

    @api.onchange('sip_enabled')
    def _make_blank_password(self):
        if self.sip_enabled:
            self.password = ''

    @api.onchange('sip_enabled', 'client_enabled')
    def set_ring_priority(self):
        if self.client_enabled and not self.sip_enabled:
            self.ring_first = 'client'
            self.ring_second = False
        elif not self.client_enabled and self.sip_enabled:
            self.ring_first = 'sip'
            self.ring_second = False
        elif self.client_enabled and self.sip_enabled:
            self.ring_first = 'client'
            self.ring_second = 'sip'
        else:
            self.ring_first = 'client'
            self.ring_second = False

    @api.onchange('ring_first')
    def on_change_ring_priority(self):
        if not self.client_enabled and not self.sip_enabled:
            return
        if self.ring_first == 'client':
            self.ring_second = 'sip'
        else:
            self.ring_second = 'client'
