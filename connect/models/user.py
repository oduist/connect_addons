# -*- coding: utf-8 -*-

import json
import jinja2
import logging
import random
import re
import string
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
if release.version_info[0] >= 19:
    from odoo.models import Constraint
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from .settings import format_connect_response, debug, strip_number, TWILIO_EDGES
from .twiml import pretty_xml

logger = logging.getLogger(__name__)


SIP_TWILIO_EDGES = TWILIO_EDGES.copy()
SIP_TWILIO_EDGES.insert(0, ['roaming', 'Global Low-latency Roaming'])

class UserCallflowCall(models.Model):
    _name = 'connect.user_callflow_call'
    _log_access = False
    _description = 'User Callflow Call'

    call = fields.Many2one('connect.call', required=True, ondelete='cascade')
    callflow = fields.Many2one('connect.user_callflow', required=True, ondelete='cascade')


class UserCallflow(models.Model):
    _name = 'connect.user_callflow'
    _description = 'User Callflow'

    user = fields.Many2one('connect.user', required=True, ondelete='cascade')
    prio = fields.Integer(required=True, default=1)
    callflow_type = fields.Char(string='Type', required=True)
    method = fields.Char(required=True)


class User(models.Model):
    _name = 'connect.user'
    _rec_name = 'username'
    _description = 'Connect User'
    _order = 'username'

    sid = fields.Char('SID', readonly=True)
    callflow = fields.One2many('connect.user_callflow', 'user')
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number', store=True)
    sip_enabled = fields.Boolean('SIP Phone Enabled')
    sip_priority = fields.Selection([('1', '1'),('2', '2')], required=True, default='2')
    client_enabled = fields.Boolean('Web Phone Enabled', default=True)
    client_priority = fields.Selection([('1', '1'),('2', '2')], required=True, default='1')
    name = fields.Char(compute='_get_name')
    user = fields.Many2one('res.users', string='Odoo User', domain=[('share', '=', False)])
    domain = fields.Many2one('connect.domain', required=True, ondelete='cascade',
                            default=lambda x: x.env['connect.domain'].search([('subdomain', 'not like', 'byoc')], limit=1))
    username = fields.Char(required=True)
    password = fields.Char(groups="connect.group_connect_admin,connect.group_connect_user")
    uri = fields.Char('SIP URI', compute='_get_sip_uri')
    connect_uri = fields.Char('SIP Connect URI', compute='_get_sip_uri')
    record_calls = fields.Boolean(default=True)
    voicemail_enabled = fields.Boolean()
    voicemail_prompt = fields.Text(default="Hello, this is {{user.name}}. I'm unable to take your call right now. Please leave a message after the tone.")
    application = fields.Many2one('connect.twiml')
    sip_ring_timeout = fields.Integer(required=True, default=30, string='SIP ring timeout')
    client_ring_timeout = fields.Integer(required=True, default=10, string='Web client ring timeout')
    callerid_number = fields.Many2one('connect.number', ondelete='restrict') # TODO: Remove after 1.0
    outgoing_callerid = fields.Many2one('connect.outgoing_callerid', ondelete='set null',
        domain=['|',('status', '=', 'validated'),('callerid_type', '=', 'number')])
    whatsapp_sender_id = fields.Many2one('connect.whatsapp_sender', string='WhatsApp Sender', ondelete='set null',
        domain="[('no_sync', '=', False), ('status', '=', 'ONLINE')]")
    missed_calls_notify = fields.Boolean(default=False, help='Notify user on missed calls.')
    greeting_message = fields.Char()
    summary_prompt = fields.Char()
    twilio_edge = fields.Selection(selection=SIP_TWILIO_EDGES, required=True, default='roaming')

    # Use modern constraint syntax for Odoo 19, fallback to legacy for older versions
    if release.version_info[0] >= 19:
        _user_uniq = Constraint('UNIQUE("user")', 'This Odoo user account is already defined!')
        _username_uniq = Constraint('UNIQUE(username)', 'This PBX username is already defined!')
    else:
        _sql_constraints = [
            ('user_uniq', 'UNIQUE("user")', 'This Odoo user account is already defined!'),
            ('username_uniq', 'UNIQUE(username)', 'This PBX username is already defined!'),
        ]

    @api.depends('username', 'domain', 'twilio_edge')
    def _get_sip_uri(self):
        settings = self.env['connect.settings']
        default_edge = settings.get_param('twilio_edge') or 'roaming'
        for rec in self:
            edge = rec.twilio_edge or default_edge
            # Render URI is always global
            rec.uri = '{}@{}'.format(rec.username, rec.domain.domain_name)
            if edge == 'roaming':
                rec.connect_uri = '{}@{}'.format(rec.username, rec.domain.domain_name)
            else:
                rec.connect_uri = '{}@{}.sip.{}.twilio.com'.format(
                    rec.username, rec.domain.subdomain, edge)

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
            elif 'already exists' in str(e):
                # Credential already exists in Twilio - import the existing SID
                debug(self, 'SIP credential {} already exists in Twilio - importing existing SID'.format(username))
                return self._import_existing_sip_credential(username, client)
            else:
                raise ValidationError(format_connect_response(e))

    def _import_existing_sip_credential(self, username, client=None):
        """Import existing SIP credential from Twilio by username.

        This is called when trying to create a credential that already exists.
        """
        self.ensure_one()
        client = client or self.env['connect.settings'].get_client()

        try:
            # Get all credentials from the domain's credential list
            credentials = client.sip.credential_lists(
                self.domain.cred_list_sid
            ).credentials.list()

            # Find the credential with matching username
            matching_credential = None
            for credential in credentials:
                if credential.username == username:
                    matching_credential = credential
                    break

            if matching_credential:
                debug(self, 'Found existing SIP credential for {} with SID {}'.format(
                    username, matching_credential.sid))
                return matching_credential.sid
            else:
                # This shouldn't happen if we got 'already exists' error
                debug(self, 'Could not find existing credential for {} in credential list'.format(
                    username), level='error')
                raise ValidationError(
                    'SIP credential "{}" already exists but could not be found in credential list'.format(username)
                )

        except Exception as e:
            debug(self, 'Error importing existing SIP credential for {}: {}'.format(
                username, str(e)), level='error')
            raise ValidationError(
                'Failed to import existing SIP credential for "{}": {}'.format(
                    username, format_connect_response(e)
                )
            )

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
        for connect_user in recs:
            connect_user.manage_group()
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
            # Check if twilio_auto_sync is disabled
            if self.env["connect.settings"].get_param("twilio_auto_sync"):
                rec.delete_sip_account()
            rec.manage_group('remove')
        res = super(User, self).unlink()
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
                debug(self, 'SIP cred {} SID {} not found in Twilio'.format(self.username, self.sid))
                self._create_sip_account(self.username, password)
            else:
                raise ValidationError(format_connect_response(e))

    @staticmethod
    def generate_twilio_password():
        """Generate a strong password for Twilio SIP credentials.

        Requirements:
        - Minimum 12 characters
        - At least one digit (0-9)
        - At least one uppercase letter (A-Z)
        - At least one lowercase letter (a-z)
        """
        # Ensure we have at least one of each required character type
        password_chars = [
            random.choice(string.ascii_lowercase),  # At least one lowercase
            random.choice(string.ascii_uppercase),  # At least one uppercase
            random.choice(string.digits),           # At least one digit
        ]

        # Fill the rest with random characters from all allowed types
        all_chars = string.ascii_letters + string.digits
        password_chars += random.choices(all_chars, k=12 - len(password_chars))

        # Shuffle to avoid predictable patterns
        random.shuffle(password_chars)

        return ''.join(password_chars)

    def manage_group(self, action='add'):
        attribute_name = 'user_ids' if release.version_info[0] >= 19 else 'users'
        if self.user and self.user.has_group('base.group_system') and self.user.has_group('base.group_erp_manager'):
            group_connect_admin = self.env.ref('connect.group_connect_admin')
            if action == 'add':
                group_connect_admin.write({attribute_name: [(4, self.user.id)]})
            else:
                group_connect_admin.with_context(install_mode=True).write({attribute_name: [(3, self.user.id)]})
        elif self.user:
            group_connect_user = self.env.ref('connect.group_connect_user')
            if action == 'add':
                group_connect_user.write({attribute_name: [(4, self.user.id)]})
            else:
                group_connect_user.with_context(install_mode=True).write({attribute_name: [(3, self.user.id)]})

    def write(self, vals):
        if 'user' in vals.keys():
            self.manage_group('remove')
        if self.env.context.get('skip_sync'):
            res = super().write(vals)
            self.manage_group()
            return res
        if 'username' in vals:
            raise ValidationError('Username cannot be changed!')
        for rec in self:
            if vals.get('password'):
                # Check if twilio_auto_sync is disabled
                if not self.env["connect.settings"].get_param("twilio_auto_sync"):
                    vals['password'] = '*' * len(vals['password'])
                else:
                    if rec.sid:
                        rec._update_sip_password(vals['password'])
                    else:
                        # SIP was enabled, create SIP user account.
                        vals['sid'] = self._create_sip_account(rec.username, vals['password'])
                    # Don't keep SIP password in Odoo.
                    vals['password'] = '*' * len(vals['password'])
        res = super().write(vals)
        self.manage_group()
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

    def _get_caller_id(self, request, params):
        caller_user = self.env['connect.user'].get_user_by_uri(request.get('Caller'))
        if caller_user:
            callerId = caller_user.exten.number or ''
            if not callerId:
                logger.warning('Exten not set for user %s', caller_user.name)
                # Get default callerid as Twilio always requires it.
                callerId = self.env['connect.outgoing_callerid'].search([('is_default', '=', True)], limit=1).number
        else:
            callerId = request.get('Caller')
        return callerId

    def _get_caller_name(self, request, params):
        caller_user = self.env['connect.user'].get_user_by_uri(request.get('Caller'))
        caller_name = params.get('CallerName', False)
        if caller_user:
            caller_name = caller_user.name


    def render_client(self, response, request, params):
        caller_name = self._get_caller_name(request, params)
        callerId = self._get_caller_id(request, params)
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].sudo().get_param('twilio_edge')
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus#e={}'.format(edge))
        status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
        dial_action_url = urljoin(api_url, 'twilio/webhook/connect.user/call_action/{}#e={}'.format(self.id, edge))
        dial_client_kwargs = {'timeout': self.client_ring_timeout, 'callerId': callerId}
        # Check for action callback URL.
        if params.get('dial_action_url'):
            dial_client_kwargs['action'] = params['dial_action_url']
        else:
            dial_client_kwargs['action'] = dial_action_url
        if self.record_calls:
            dial_client_kwargs.update({
                'record': 'record-from-answer-dual',
                'recordingStatusCallback': record_status_url
            })
        dial_client = Dial(**dial_client_kwargs)
        client = Client(
            statusCallbackEvent='initiated answered completed',
            statusCallback=status_url)
        client.identity(self.get_client_identity())
        if caller_name:
            client.parameter(name='CallerName', value=caller_name)
        channel = self.env['connect.channel'].search([('sid', '=', request.get('CallSid'))])
        call = channel.call
        if call and call.partner:
            partner_id = call.partner.id
            if not caller_name:
                client.parameter(name="CallerName", value=call.partner.name)
        elif channel and channel.caller_user:
            partner_id = channel.caller_user.partner_id.id
            if not caller_name:
                client.parameter(name="CallerName", value=channel.caller_user.partner_id.name)
        else:
            partner_id = False
        client.parameter(name='Partner', value=partner_id)
        dial_client.append(client)
        response.append(dial_client)

    def render_sip(self, response, request, params):
        callerId = self._get_caller_id(request, params)
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].get_param('twilio_edge')
        dial_action_url = urljoin(api_url, 'twilio/webhook/connect.user/call_action/{}#e={}'.format(self.id, edge))
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus#e={}'.format(edge))
        status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
        dial_sip_kwargs = {'timeout': self.sip_ring_timeout, 'callerId': callerId}
        # Check for action callback URL.
        if params.get('dial_action_url'):
            dial_sip_kwargs['action'] = params['dial_action_url']
        else:
            dial_sip_kwargs['action'] = dial_action_url
        if self.record_calls:
            dial_sip_kwargs.update({
                'recordingStatusCallback': record_status_url,
                'record': 'record-from-answer-dual'
            })
        dial_sip = Dial(**dial_sip_kwargs)
        dial_sip.sip(
            'sip:{}{}'.format(self.uri, ';secure=true' if self.domain.secure_media else ''),
            statusCallbackEvent='initiated answered completed',
            statusCallback=status_url)
        response.append(dial_sip)


    def render_voicemail(self, response, request, params):
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].sudo().get_param('twilio_edge')
        voicemail_record_status_url = urljoin(api_url, 'twilio/webhook/vm_recordingstatus#e={}'.format(edge))
        self.get_voicemail_prompt(response)
        response.record(
            maxLength=120,
            finishOnKey='#',
            playBeep=True,
            recordingStatusCallback=voicemail_record_status_url)

    def render(self, request={}, params={}):
        self.ensure_one()
        channel = self.env['connect.channel'].search(
            [('sid', '=', request.get('CallSid'))], order='id desc')
        call = channel.call
        response = VoiceResponse()
        # Check if this is real a call or dialplan view render.
        if call:
            done_callflow_ids = self.env['connect.user_callflow_call'].sudo().search(
                [('call', '=', call.id)]).mapped('callflow').mapped('id')
            if not done_callflow_ids and self.greeting_message:
                # First attempt. Greet the caller if required.
                self.get_greeting_message(response)
            next_call_flow = self.env['connect.user_callflow'].sudo().search(
                [('user', '=', self.id), ('id', 'not in', done_callflow_ids)], order='prio', limit=1)
            if next_call_flow:
                self.env['connect.user_callflow_call'].sudo().create({
                    'call': call.id,
                    'callflow': next_call_flow.id,
                })
                # Call the method
                getattr(self, next_call_flow.method)(response, request, params)
                debug(self, pretty_xml(response.to_xml()))
                return response.to_xml()
            else:
                # Cleanup.
                callflows = self.env['connect.user_callflow_call'].sudo().search(
                    [('call', '=', call.id)])
                callflows.sudo().unlink()
                response.hangup()
                return response.to_xml()
        else:
            # Dialplan view render, just render all one by one
            all_flows = self.env['connect.user_callflow'].sudo().search([('user', '=', self.id)], order='prio')
            for flow in all_flows:
                getattr(self, flow.method)(response, request, params)
            return response.to_xml()

    def get_client_identity(self):
        # Clients always user global domain.
        return '{}@{}'.format(self.username, self.domain.domain_name)

    @api.model
    def get_client_token(self):
        try:
            has_user_group = self.env.user.has_group('connect.group_connect_user')
            has_admin_group = self.env.user.has_group('connect.group_connect_admin')
            if not (has_user_group or has_admin_group):
                return {'token': False}
            user = self.search([('user', '=', self.env.user.id)])
            if not user:
                logger.info("User %s not found!", self.env.user.id)
                return {'token': False}
            if not user.client_enabled:
                logger.info("Client for user %s not enabled!", self.env.user.id)
                return {'token': False}
            account_sid = self.env['connect.settings'].sudo().get_param('account_sid')
            api_key = self.env['connect.settings'].sudo().get_param('twilio_api_key')
            api_secret = self.env['connect.settings'].sudo().get_param('twilio_api_secret')
            identity = user.get_client_identity()
            token = AccessToken(account_sid, api_key, api_secret, identity=identity, ttl=3600,
                region=self.env['connect.settings'].sudo().get_param('twilio_region'),
            )
            voice_grant = VoiceGrant(
                outgoing_application_sid=user.application.sid or user.domain.application.sid,
                outgoing_application_params={},
                incoming_allow=True,
            )
            token.add_grant(voice_grant)
            return {
                'token': token.to_jwt(),
                'edge': user.twilio_edge or self.env['connect.settings'].sudo().get_param('twilio_edge'),
            }
        except Exception as e:
            logger.exception('Error getting Twilio JWT:')
            return {'error': str(e)}

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
    def get_user_by_uri(self, userinfo):
        if not userinfo:
            # Return empty set.
            return self.env['connect.user']
        re_call_uri = re.compile(r'^(?:sip|client):([^@]+)@')
        found_username = re_call_uri.search(userinfo)
        if found_username:
            user = self.env['connect.user'].search([
                ('username', '=', found_username.group(1))])
            debug(self, 'Found user: {} by {}.'.format(user.username, userinfo))
            return user
        # Return empty set.
        return self.env['connect.user']

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'user')

    @api.model
    def on_call_action(self, record_id, request):
        # Was used for VoiceMail. Left for future features.
        user = self.browse(record_id)
        call_status = request.get('CallStatus')
        if not call_status:
            # VoiceMail
            call_status = request.get('DialCallStatus')
        if call_status != 'completed':
            dialplan = user.render(request)
            return dialplan
        else:
            response = VoiceResponse()
            response.hangup()
            return response.to_xml()

    def get_greeting_message(self, response):
        # Override in Elevenlabs module.
        self.ensure_one()
        response.say(self.greeting_message)

    def get_voicemail_prompt(self, response):
        self.ensure_one()
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

    def _manage_channel_callflow(self, channel, enable):
        if enable:
            callflow = self.env['connect.user_callflow'].search(
                    [('user', '=', self.id), ('callflow_type', '=', channel)])
            if not callflow:
                self.env['connect.user_callflow'].create({
                    'user': self.id,
                    'callflow_type': channel,
                    'prio': int(getattr(self, '{}_priority'.format(channel))),
                    'method': 'render_{}'.format(channel),
                })
            else:
                # Existing record, change prio
                callflow.prio = getattr(self, '{}_priority'.format(channel))
        else:
            # Disabled
            self.env['connect.user_callflow'].search(
                [('user', '=', self.id), ('callflow_type', '=', channel)]).unlink()


    @api.constrains('sip_enabled', 'sip_priority')
    def _manage_sip_callflow(self):
        if self.sip_enabled:
            self._manage_channel_callflow('sip', True)
        else:
            self._manage_channel_callflow('sip', False)

    @api.constrains('client_enabled', 'client_priority')
    def _manage_client_callflow(self):
        if self.client_enabled:
            self._manage_channel_callflow('client', True)
        else:
            self._manage_channel_callflow('client', False)

    @api.constrains('voicemail_enabled')
    def _manage_voicemail_enabled(self):
        if self.voicemail_enabled:
            if not self.env['connect.user_callflow'].search(
                    [('user', '=', self.id), ('callflow_type', '=', 'voicemail')]):
                self.env['connect.user_callflow'].create({
                    'user': self.id,
                    'prio': 10,
                    'callflow_type': 'voicemail',
                    'method': 'render_voicemail'
                })
        else:
            self.env['connect.user_callflow'].search(
                [('user', '=', self.id), ('callflow_type', '=', 'voicemail')]).unlink()
