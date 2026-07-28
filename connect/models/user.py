# -*- coding: utf-8 -*-

import json
import jinja2
import logging
import random
import re
import string
from datetime import timedelta
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
if release.version_info[0] >= 19:
    from odoo.models import Constraint
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from .settings import format_connect_response, debug, TWILIO_EDGES
from .twiml import pretty_xml

logger = logging.getLogger(__name__)

AUTO_ANSWER_HEADERS = [
    ('X-AUTOANSWER=TRUE', 'X-AUTOANSWER=TRUE'),
    ('Call-Info=answer-after%3D0', 'Call-Info=answer-after=0'),
    ('Call-Info=Auto%20Answer', 'Call-Info=Auto Answer'),
]

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
    pbx_group_ids = fields.Many2many('connect.pbx_group', string='PBX Groups')
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
    auto_answer_header = fields.Selection(AUTO_ANSWER_HEADERS)
    fallback_destination = fields.Selection([
        ('mobile', 'Mobile'),
    ])
    fallback_destination_mobile = fields.Char('Mobile Phone')
    fallback_destination_exten = fields.Many2one('connect.exten')
    call_popup_is_enabled = fields.Boolean(default=True, string='Enable Call Notifications', help='Enable notifications for call events')
    call_popup_is_sticky = fields.Boolean(default=False, string='Sticky Call Notifications', help='Require manual dismissal of call notifications?')
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

    def _get_transferring_pbx_user(self, call):
        """Find the PBX user who is transferring the call (the last user who answered before transfer)."""
        if call.answered_pbx_user:
            return call.answered_pbx_user
        # answered_pbx_user not yet set (finalization hasn't run), find from channels
        completed_channels = call.channels.filtered(
            lambda c: c.called_pbx_user and c.status in ('completed', 'in-progress')
                      and c.called_pbx_user.user not in call.transferred_users
        )
        if completed_channels:
            return completed_channels.sorted('id')[0].called_pbx_user
        return None

    def _get_caller_name(self, request, params):
        caller_user = self.env['connect.user'].get_user_by_uri(request.get('Caller'))
        caller_name = params.get('CallerName', False)
        if caller_user:
            caller_name = caller_user.name
        return caller_name

    def _ensure_direct_call_attempt(self, call, params):
        """Record the leg expected from a synchronous Dial response."""
        if not call or params.get('_is_transfer_redirect'):
            return
        pending = call.attempt_ids.filtered(
            lambda attempt: attempt.kind == 'direct_call'
            and attempt.state == 'pending'
            and attempt.target_user_id == self.user
        )[:1]
        if not pending:
            call._set_webhook_expectation('direct_call', {
                'expected_count': 1,
                'target_user_id': self.user.id,
            })

    def render_client(self, response, request, params):
        caller_name = self._get_caller_name(request, params)
        callerId = self._get_caller_id(request, params)
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].sudo().get_param('twilio_edge')
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus#e={}'.format(edge))
        status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
        dial_action_url = urljoin(api_url, 'twilio/webhook/connect.user/call_action/{}#e={}'.format(self.id, edge))
        # For transfer redirects, use dial_complete for completion tracking
        if params.get('_is_transfer_redirect'):
            dial_action_url = urljoin(api_url, 'connect/dial_complete#e={}'.format(edge))
        # For transfers, show the original caller to the transfer recipient
        channel = self.env['connect.channel'].search([('sid', '=', request.get('CallSid'))])
        call = channel.call if channel else None
        if call and call.transferred_users:
            if call.caller_pbx_user and call.caller_pbx_user.exten:
                callerId = call.caller_pbx_user.exten.number or callerId
                caller_name = call.caller_pbx_user.name or caller_name
            elif call.caller:
                callerId = call.caller or callerId
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
        if not channel:
            channel = self.env['connect.channel'].search([('sid', '=', request.get('CallSid'))])
            call = channel.call if channel else None
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
        self._ensure_direct_call_attempt(call, params)
        response.append(dial_client)

    def render_sip(self, response, request, params):
        callerId = self._get_caller_id(request, params)
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].get_param('twilio_edge')
        dial_action_url = urljoin(api_url, 'twilio/webhook/connect.user/call_action/{}#e={}'.format(self.id, edge))
        # For transfer redirects, use dial_complete for completion tracking
        if params.get('_is_transfer_redirect'):
            dial_action_url = urljoin(api_url, 'connect/dial_complete#e={}'.format(edge))
        # For transfers, use the transferring user's caller ID instead of the original caller
        channel = self.env['connect.channel'].search([('sid', '=', request.get('CallSid'))])
        call = channel.call if channel else None
        if call and call.transferred_users:
            transferring_user = self._get_transferring_pbx_user(call)
            if transferring_user:
                callerId = transferring_user.exten.number or callerId
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus#e={}'.format(edge))
        status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
        refer_url = urljoin(api_url, 'twilio/webhook/sip_refer#e={}'.format(edge))
        dial_sip_kwargs = {'timeout': self.sip_ring_timeout, 'callerId': callerId, 'referUrl': refer_url}
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
        self._ensure_direct_call_attempt(call, params)
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
        # TRANSFER DETECTION
        is_transfer_redirect = self._detect_transfer_redirect(request, params, call)
        if is_transfer_redirect:
            original_call = self._find_original_call_for_transfer(request, params)
            if original_call:
                if self.user:
                    original_call.add_transferred_user(self.user)
                    original_call.store_transfer_context(request.get('CallSid'), self.user)
        if is_transfer_redirect:
            params = dict(params)
            params['_is_transfer_redirect'] = True
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
    def handle_sip_refer(self, request):
        """Handle SIP REFER webhook from Twilio.

        When a SIP phone initiates a transfer, Twilio sends a webhook with
        ReferTransferTarget containing the SIP URI of the transfer target.
        For attended transfers, the Replaces parameter identifies the
        consultation call that must be terminated.
        """
        refer_target = request.get('ReferTransferTarget', '')
        logger.info('SIP REFER received: ReferTransferTarget=%s, CallSid=%s', refer_target, request.get('CallSid'))
        # Parse extension from SIP URI: sip:1002@domain.sip.twilio.com
        # or <sip:1002@domain.sip.twilio.com?Replaces=...>
        found = re.search(r'sip:([^@]+)@', refer_target)
        if not found:
            logger.warning('SIP REFER: could not parse target from %s', refer_target)
            return '<Response><Say>Transfer target not found.</Say></Response>'
        target_number = found.group(1)
        logger.info('SIP REFER: parsed target extension %s', target_number)

        # For attended transfers, terminate the consultation call identified
        # by the Replaces SipCallId so the transferring agent is released.
        replaces_match = re.search(r'Replaces=([^%;&>]+)', refer_target)
        if replaces_match:
            replaces_sip_call_id = replaces_match.group(1)
            logger.info('SIP REFER: attended transfer, Replaces SipCallId=%s', replaces_sip_call_id)
            self._terminate_consultation_call(replaces_sip_call_id)

        exten = self.env['connect.exten'].sudo().search([('number', '=', target_number)], limit=1)
        if not exten:
            logger.warning('SIP REFER: extension %s not found', target_number)
            return '<Response><Say>Extension not found.</Say></Response>'

        return exten.render(request=request, params={})

    @api.model
    def _terminate_consultation_call(self, sip_call_id):
        """Terminate the consultation call by its SipCallId.

        During attended transfer, the transferring agent's consultation call
        must be ended so their SIP phone is released.
        We find the channel by matching SipCallId stored during creation.
        """
        try:
            channel = self.env['connect.channel'].sudo().search([
                ('sip_call_id', '=', sip_call_id),
                ('status', 'not in', ['completed', 'canceled', 'busy', 'no-answer', 'failed']),
            ], limit=1)
            if channel:
                logger.info('SIP REFER: found consultation channel %s (CallSid=%s), terminating',
                            channel.id, channel.sid)
                client = self.env['connect.settings'].get_client()
                client.calls(channel.sid).update(status='completed')
                return
            logger.warning('SIP REFER: consultation call with SipCallId=%s not found', sip_call_id)
        except Exception as e:
            logger.error('SIP REFER: failed to terminate consultation call: %s', e)

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
        response = VoiceResponse()
        user = self.browse(record_id)
        
        if request.get('DialCallStatus') == 'completed':
            response.hangup()
        else:
            if user.voicemail_enabled:
                api_url = self.env['connect.settings'].sudo().get_param('api_url')
                edge = self.env['connect.settings'].sudo().get_param('twilio_edge')
                record_status_url = urljoin(api_url, 'twilio/webhook/vm_recordingstatus#e={}'.format(edge))
                response.pause(length=1)
                if user.voicemail_prompt:
                    personalized_prompt = user.render_voicemail_prompt()
                    system_voice = self.env['connect.settings'].get_system_voice()
                    processed_text = self.env['connect.settings'].process_pronunciation(personalized_prompt)
                    response.say(processed_text, voice=system_voice)
                else:
                    generic_prompt = f'{user.name} is not available. Please leave a message.'
                    system_voice = self.env['connect.settings'].get_system_voice()
                    processed_text = self.env['connect.settings'].process_pronunciation(generic_prompt)
                    response.say(processed_text, voice=system_voice)
                response.record(
                    maxLength=120,
                    finishOnKey='#',
                    playBeep=True,
                    recordingStatusCallback=record_status_url)
            else:
                system_voice = self.env['connect.settings'].get_system_voice()
                processed_text = self.env['connect.settings'].process_pronunciation('Sorry, there is no voicemail set up. Please try again later. Goodbye!')
                response.say(processed_text, voice=system_voice)
                response.pause(length=1)
                response.hangup()
        
        debug(self, pretty_xml(str(response)))
        return response

    def get_greeting_message(self, response):
        self.ensure_one()
        system_voice = self.env['connect.settings'].get_system_voice()
        processed_text = self.env['connect.settings'].process_pronunciation(self.greeting_message)
        response.say(processed_text, voice=system_voice)

    def get_voicemail_prompt(self, response):
        self.ensure_one()
        voicemail_prompt = self.render_voicemail_prompt()
        system_voice = self.env['connect.settings'].get_system_voice()
        processed_text = self.env['connect.settings'].process_pronunciation(voicemail_prompt)
        response.say(processed_text, voice=system_voice)

    def render_voicemail_prompt(self):
        self.ensure_one()
        # Render user greeting.
        environment = jinja2.Environment()
        template = environment.from_string(self.voicemail_prompt)
        return template.render({'user': self})

    def _detect_transfer_redirect(self, request, params, call):
        call_sid = request.get('CallSid')
        if not call_sid:
            return False
        if call:
            return False
        recent_transfers = self.env['connect.call'].search([
            ('transferred_users', '!=', False),
            ('create_date', '>=', fields.Datetime.now() - timedelta(minutes=5))
        ])
        if recent_transfers:
            return True
        return False

    def _find_original_call_for_transfer(self, request, params):
        call_sid = request.get('CallSid')
        if self.user:
            potential_calls = self.env['connect.call'].search([
                ('transferred_users', 'in', [self.user.id]),
                ('create_date', '>=', fields.Datetime.now() - timedelta(minutes=5))
            ])
            for call in potential_calls:
                existing_channel = call.channels.filtered(lambda c: c.sid == call_sid)
                if not existing_channel:
                    return call
        recent_calls = self.env['connect.call'].search([
            ('transferred_users', '!=', False),
            ('create_date', '>=', fields.Datetime.now() - timedelta(minutes=5)),
            ('status', 'not in', ['completed', 'failed', 'busy', 'no-answer'])
        ])
        for call in recent_calls:
            transfer_completed = False
            for user in call.transferred_users:
                user_channels = call.channels.filtered(lambda c: c.called_user and c.called_user.id == user.id)
                if user_channels.filtered(lambda c: c.status == 'completed'):
                    transfer_completed = True
                    break
            if not transfer_completed:
                return call
        logger.warning(f'Could not find original call for transfer redirect SID {call_sid}')
        return None

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

    def render_fallback_destination(self, response, request, params):
        if self.fallback_destination:
            api_url = self.env['connect.settings'].sudo().get_param('api_url')
            record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus')
            status_url = urljoin(api_url, 'twilio/webhook/callstatus')
            dial_action_url = urljoin(api_url, 'twilio/webhook/connect.user/call_action/{}'.format(self.id))
            if self.fallback_destination == 'mobile':
                dial_mobile_kwargs = {
                    'timeout': 60,
                    'callerId': self.outgoing_callerid.number,
                }
                if params.get('dial_action_url'):
                    dial_mobile_kwargs['action'] = params['dial_action_url']
                else:
                    dial_mobile_kwargs['action'] = dial_action_url
                if self.record_calls:
                    dial_mobile_kwargs.update({
                        'recordingStatusCallback': record_status_url,
                        'record': 'record-from-answer-dual'
                    })
                dial = Dial('+{}'.format(strip_number(
                    self.fallback_destination_mobile)), **dial_mobile_kwargs)
                response.say('Connecting...')
                response.append(dial)
            elif self.fallback_destination == 'exten':
                raise Exception('Not implemented')

    @api.onchange('fallback_destination')
    def _set_fallback_destination_mobile(self):
        if self.fallback_destination == 'mobile' and not self.fallback_destination_mobile:
            self.fallback_destination_mobile = self.user.partner_id.mobile

    @api.constrains('fallback_destination')
    def _manage_fallback_destination_callflow(self):
        if self.fallback_destination:
            if not self.env['connect.user_callflow'].search(
                    [('user', '=', self.id), ('callflow_type', '=', 'fallback_destination')]):
                self.env['connect.user_callflow'].create({
                    'user': self.id,
                    'prio': 5,
                    'callflow_type': 'fallback_destination',
                    'method': 'render_fallback_destination'
                })
        else:
            self.env['connect.user_callflow'].search(
                [('user', '=', self.id), ('callflow_type', '=', 'fallback_destination')]).unlink()

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
