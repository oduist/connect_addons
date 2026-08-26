# -*- coding: utf-8 -*-

import json
import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from .settings import debug

CALL_END_STATUSES = ['completed', 'busy', 'failed', 'no-answer', 'canceled']

logger = logging.getLogger(__name__)


class Channel(models.Model):
    _name = 'connect.channel'
    _description = 'Channel'
    _inherit = 'mail.thread'
    _rec_name = 'id'
    _order = 'id desc'

    call = fields.Many2one('connect.call', ondelete='cascade')
    sid = fields.Char('SID', readonly=True, index=True)
    parent_channel = fields.Many2one('connect.channel', ondelete='cascade', tracking=True)
    parent_sid = fields.Char('Parent SID', tracking=True, readonly=True, index=True)
    partner = fields.Many2one('res.partner', ondelete='set null', tracking=True)
    called = fields.Char(tracking=True)
    to = fields.Char(tracking=True)
    technical_direction = fields.Char(tracking=True, string='Direction')
    status = fields.Char(tracking=True)
    duration = fields.Integer(string='Seconds', tracking=True)
    duration_minutes = fields.Float(string='Minutes', tracking=True)
    duration_billing = fields.Integer(string='Bill Minutes', tracking=True)
    duration_human = fields.Char(compute='_get_duration_human', string='Duration', store=True, tracking=True)
    caller = fields.Char(tracking=True)
    call_type = fields.Selection([
        ('phone', 'Phone'),
        ('whatsapp', 'WhatsApp')
    ], default='phone', index=True, tracking=True)
    # PBX users are Connect SIP or Client users.
    caller_pbx_user = fields.Many2one('connect.user', ondelete='set null', string='Caller PBX User', tracking=True)
    called_pbx_user = fields.Many2one('connect.user', ondelete='set null', string='Called PBX User', tracking=True)
    # Users are Odoo accounts.
    caller_user = fields.Many2one('res.users', string='Caller User', tracking=True)
    called_user = fields.Many2one('res.users', string='Called User', tracking=True)
    # Parsed numbers (domain stripped).
    caller_number = fields.Char(compute='_get_channel_numbers', store=True, index=True)
    called_number = fields.Char(compute='_get_channel_numbers', store=True, index=True)
    # Call source tracking for pattern detection
    call_source = fields.Selection([
        ('direct_call', 'Direct Call'),
        ('ring_group', 'Ring Group'),
        ('transfer', 'Transfer'),
        ('external_dial', 'External Dial')
    ], string='Call Source', help='How this channel was created', tracking=True)
    # SIP Call-ID for matching SIP REFER Replaces header
    sip_call_id = fields.Char('SIP Call-ID', index=True)
    # Webhook sequence tracking for duplicate filtering
    sequence_number = fields.Integer(string='Sequence Number', default=0, help='Twilio webhook sequence number for duplicate filtering')
    pbx_group_user_ids = fields.Many2many(
        'res.users', 'connect_channel_pbx_group_users_rel',
        string='PBX Group Users',
        compute='_compute_pbx_group_user_ids', store=True)

    @api.depends('caller_user', 'called_user')
    def _compute_pbx_group_user_ids(self):
        for rec in self:
            users = self.env['res.users']
            for u in (rec.caller_user, rec.called_user):
                if u and u.connect_user:
                    for group in u.connect_user.pbx_group_ids:
                        users |= group.user_ids
            rec.pbx_group_user_ids = users

    @api.depends('caller', 'called')
    def _get_channel_numbers(self):
        re_number_domain = re.compile(r'^(sip|client):(.+)@(.+)$')
        re_client_number = re.compile(r'^client:(\d{8})$')
        re_number = re.compile(r'^(\+?[0-9]+)$')
        re_whatsapp = re.compile(r'^whatsapp:(\+?[0-9]+)$')

        def _get_number(callinfo):
            if not isinstance(callinfo, str):
                return ''
            if re_number.search(callinfo):
                return callinfo
            elif re_whatsapp.search(callinfo):
                # Strip whatsapp: prefix, keep E.164 number
                return re_whatsapp.search(callinfo).group(1)
            elif re_number_domain.search(callinfo):
                user_or_number = re_number_domain.search(callinfo).group(2)
                # Substitute username to his number
                user = self.env['connect.user'].get_user_by_uri(callinfo)
                if user:
                    return user.exten.number
                else:
                    return user_or_number
            elif re_client_number.search(callinfo):
                return re_client_number.search(callinfo).group(1)
            else:
                # We should not be here.
                return ''

        for rec in self:
            rec.caller_number = _get_number(rec.caller)
            rec.called_number = _get_number(rec.called)

    @api.depends('duration')
    def _get_duration_human(self):
        for record in self:
            if record.duration is not None:
                minutes = record.duration // 60
                seconds = record.duration % 60
                record.duration_human = '{:02}:{:02}'.format(minutes, seconds)
                record.duration_minutes = record.duration / 60.0
            else:
                record.duration_minutes = 0
                record.duration_human = "00:00"

    @api.model
    def on_call_status(self, params):
        debug(self, 'On channel status: %s' % json.dumps(params, indent=2))
        # Pre-process for WhatsApp and E.164 normalization
        def strip_whatsapp(v):
            return v.split(':', 1)[1] if isinstance(v, str) and v.startswith('whatsapp:') else v
        caller_raw = params.get('Caller')
        called_raw = params.get('Called')
        to_raw = params.get('To')
        caller_clean = strip_whatsapp(caller_raw)
        called_clean = strip_whatsapp(called_raw)
        to_clean = strip_whatsapp(to_raw)
        call_type = 'whatsapp' if any(isinstance(x, str) and x.startswith('whatsapp:') for x in [caller_raw, called_raw, to_raw]) else 'phone'

        # ENHANCED BLIND TRANSFER LOGGING
        logger.info(f"=== WEBHOOK RECEIVED ===")
        logger.info(f"CallSid: {params.get('CallSid')}")
        logger.info(f"CallStatus: {params.get('CallStatus')}")
        logger.info(f"Direction: {params.get('Direction')}")
        logger.info(f"From: {params.get('From')} | To: {params.get('To')}")
        logger.info(f"Called: {params.get('Called')} | Caller: {params.get('Caller')}")
        logger.info(f"ParentCallSid: {params.get('ParentCallSid')}")
        logger.info(f"Duration: {params.get('CallDuration', 0)}")
        logger.info(f"SequenceNumber: {params.get('SequenceNumber')}")
        logger.info(f"=== END WEBHOOK INFO ===")

        # SEQUENCE-BASED DUPLICATE FILTERING: Check for duplicate webhooks
        call_sid = params.get('CallSid')
        sequence_number = int(params.get('SequenceNumber', 0))
        call_status = params.get('CallStatus')

        # Look for existing channels with same CallSid
        channel = self.search([('sid', '=', call_sid)])
        if channel:
            # Allow webhooks with newer sequence numbers OR same sequence with different status (legitimate status updates)
            if sequence_number < channel.sequence_number or (sequence_number == channel.sequence_number and call_status == channel.status):
                logger.warning(f"DUPLICATE WEBHOOK FILTERED: CallSid {call_sid} SequenceNumber {sequence_number} (existing: {channel.sequence_number}) CallStatus {call_status} (existing: {channel.status}) - ignoring webhook")
                return
            else:
                logger.info(f"VALID WEBHOOK: CallSid {call_sid} SequenceNumber {sequence_number} CallStatus {call_status} - processing status update")
        if channel:
            # Update channel data.
            data = {
                'technical_direction': params['Direction'],
                'status': params['CallStatus'],
                'duration': int(params.get('CallDuration', 0)),
                'call_type': call_type,
                'sequence_number': sequence_number,
            }
            # Only overwrite caller/called/to when webhook provides non-empty values
            # to prevent Twilio completion callbacks from blanking identity fields.
            if caller_clean:
                data['caller'] = caller_clean
            if called_clean:
                data['called'] = called_clean
            if to_clean:
                data['to'] = to_clean
            # Find an existing parent channel.
            if not channel.parent_channel:
                # Check if channel has parent_sid without channel
                if channel.parent_sid:
                    parent_channel = self.search([('sid', '=', channel.parent_sid)])
                    data['parent_channel'] = parent_channel.id
                elif params.get('ParentCallSid'):
                    parent_channel = self.search([('sid', '=', params.get('ParentCallSid'))])
                    data['parent_channel'] = parent_channel.id
                    data['parent_sid'] = parent_channel.parent_channel.sid
            channel.write(data)
            debug(self, 'Channel %s updated.' % channel.id)

            # Check for external call termination after transfer recipient hangs up
            if params['CallStatus'] in CALL_END_STATUSES and channel.call:
                self._handle_external_call_termination_on_hangup(channel, params)

            # Note: Outgoing transfer failures now handled by direct extension redirect
            # No longer need complex failure detection logic
        # Channel not found by sid, create it.
        else:
            data = {
                'sid': params['CallSid'],
                'called': called_clean,
                'to': to_clean,
                'technical_direction': params['Direction'],
                'status': params['CallStatus'],
                'duration': int(params.get('CallDuration', 0)),
                'caller': caller_clean,
                'call_type': call_type,
                'sequence_number': sequence_number,
            }
            # Store SIP Call-ID for attended transfer matching
            if params.get('SipCallId'):
                data['sip_call_id'] = params['SipCallId']
            # Check if channel has parent_sid without channel
            if channel.parent_sid:
                parent_channel = self.search([('sid', '=', channel.parent_sid)])
                data['parent_channel'] = parent_channel.id
            elif params.get('ParentCallSid'):
                parent_channel = self.search([('sid', '=', params.get('ParentCallSid'))])
                if parent_channel:
                    data['parent_channel'] = parent_channel.id
                    data['parent_sid'] = parent_channel.parent_channel.sid
                else:
                    logger.warning(f"NEW CHANNEL: ParentCallSid {params.get('ParentCallSid')} not found in existing channels!")
            # Find caller user
            caller_pbx_user = None
            called_pbx_user = None
            if params.get('Caller'):
                caller_pbx_user = self.env['connect.user'].get_user_by_uri(params['Caller'])
                data['caller_pbx_user'] = caller_pbx_user.id
                data['caller_user'] = caller_pbx_user.user.id
            # Find called user
            if params.get('Called'):
                called_pbx_user = self.env['connect.user'].get_user_by_uri(params['Called'])
                data['called_pbx_user'] = called_pbx_user.id
                data['called_user'] = called_pbx_user.user.id
            # Find the partner (use cleaned numbers)
            if caller_pbx_user and called_clean:
                # User makes outgoing call.
                if (called_clean or '').startswith('+') or (called_clean or '').startswith('sip:+'):
                    data['partner'] = self.env['res.partner'].get_partner_by_number(called_clean).id
                    debug(self, 'Setting partner caller user by called.')
            elif called_pbx_user and caller_clean:
                if (caller_clean or '').startswith('+'):
                    data['partner'] = self.env['res.partner'].get_partner_by_number(caller_clean).id
                    debug(self, 'Setting partner called user by caller.')
            elif params.get('Direction') == 'outbound-dial' and called_clean:
                    data['partner'] = self.env['res.partner'].get_partner_by_number(called_clean).id
                    debug(self, 'Setting partner for outbound dial by called.')
            elif params.get('Direction') == 'inbound' and \
                    (called_clean or '').startswith('+') and (caller_clean or '').startswith('+'):
                debug(self, 'Incoming DID/WhatsApp call. Get the partner from caller number.')
                data['partner'] = self.env['res.partner'].get_partner_by_number(caller_clean).id
            else:
                debug(self, 'Not setting channel partner without channel users.')

            # EXPLICIT CHANNEL TAGGING: Set call_source based on call context
            if data.get('parent_channel'):
                # This is a child channel, determine source from parent call pattern
                parent_channel_obj = self.browse(data['parent_channel'])
                if parent_channel_obj.call and parent_channel_obj.call.call_pattern:
                    if parent_channel_obj.call.call_pattern == 'ring_group':
                        # Check if this channel's user is a transfer recipient or ring group participant
                        if parent_channel_obj.call.transferred_users and data.get('called_pbx_user'):
                            # Check if this specific user is a transfer recipient
                            called_pbx_user_obj = self.env['connect.user'].browse(data['called_pbx_user'])
                            if called_pbx_user_obj.user and called_pbx_user_obj.user in parent_channel_obj.call.transferred_users:
                                data['call_source'] = 'transfer'
                            else:
                                data['call_source'] = 'ring_group'
                        else:
                            data['call_source'] = 'ring_group'
                    elif parent_channel_obj.call.call_pattern == 'direct_call':
                        # For direct calls, child channels are either initial direct calls, transfers, or external dials
                        if parent_channel_obj.call.transferred_users:
                            # Call has transfers - new child channels are likely transfers
                            data['call_source'] = 'transfer'
                        elif (params.get('Called', '').startswith('client:') or
                              params.get('Called', '').startswith('sip:')):
                            data['call_source'] = 'direct_call'  # Initial direct call
                        else:
                            data['call_source'] = 'external_dial'  # External number
            else:
                # This is a parent channel (inbound call)
                data['call_source'] = None  # Will be set when pattern is determined

            channel = self.with_context(tracking_disable=True).create(data)
            debug(self, 'Channel %s created.' % channel.id)

            # Store external call leg for outgoing call transfers
            if (params.get('Direction') == 'outbound-dial' and
                data.get('parent_channel') and
                params.get('CallSid')):

                parent_channel = self.browse(data['parent_channel'])
                if parent_channel.call and parent_channel.call.direction == 'outgoing':
                    # This is the external call leg for an outgoing call - store it for transfers
                    parent_channel.call.store_external_call_leg(params['CallSid'])
        return channel

    def _handle_failed_outgoing_transfer(self, channel, params):
        """
        Detect when an outgoing call transfer target fails (no-answer, busy, failed, canceled)
        and redirect the external caller to the transfer target's voicemail.
        """
        # Only handle outbound-api calls (transfer target calls) with failure statuses
        if (params.get('Direction') != 'outbound-api' or
            params.get('CallStatus') not in ['no-answer', 'busy', 'failed', 'canceled']):
            return

        # Only handle channels that have a called_pbx_user (transfer targets)
        if not channel.called_pbx_user:
            return

        # Check if this is a transfer target call by looking for the transfer context
        if not channel.call or channel.call.direction != 'outgoing':
            return

        # This appears to be a failed outgoing transfer target
        logger.info(f'=== DETECTED FAILED OUTGOING TRANSFER TARGET ===')
        logger.info(f'Channel: {channel.id}, SID: {channel.sid}')
        logger.info(f'Status: {params.get("CallStatus")}, Target: {channel.called_pbx_user.name}')
        logger.info(f'Call: {channel.call.id}, Direction: {channel.call.direction}')

        try:
            # Get the external call leg that needs to be redirected to voicemail
            external_call_sid = channel.call.get_external_call_leg()
            if not external_call_sid:
                logger.warning(f'Could not find external call leg for failed transfer')
                return

            # Use Twilio client to redirect the external caller to the target's extension
            client = self.env['connect.settings'].get_client()

            # Get the target user's extension URL for voicemail
            target_user = channel.called_pbx_user
            api_url = self.env['connect.settings'].sudo().get_param('api_url')
            extension_url = urljoin(api_url, f'connect/{target_user.exten.number}')

            logger.info(f'Redirecting external call {external_call_sid} to {target_user.name} extension: {extension_url}')

            # Redirect the external call to the target's extension for voicemail
            client.calls(external_call_sid).update(url=extension_url, method='GET')

            logger.info(f'Successfully redirected external caller to voicemail')
            logger.info(f'=== END FAILED TRANSFER HANDLING ===')

        except Exception as e:
            logger.error(f'Error handling failed outgoing transfer: {e}')

    def _handle_external_call_termination_on_hangup(self, channel, params):
        """
        Handle external call termination when transfer recipients hang up completed calls.
        This prevents external callers from going to voicemail when internal users end calls.
        """
        try:
            call = channel.call
            call_sid = params.get('CallSid')
            call_status = params.get('CallStatus')

            # Only process if call has transfer context with termination info
            if not call.transfer_context or '_external_termination' not in call.transfer_context:
                return

            termination_info = call.transfer_context['_external_termination']
            transfer_recipient_sid = termination_info.get('transfer_recipient_sid')
            external_call_sid = termination_info.get('external_call_sid')

            # Check if this is the transfer recipient hanging up
            if call_sid == transfer_recipient_sid:
                # Terminate the external call
                client = self.env['connect.settings'].get_client()
                try:
                    # Check if external call is still active
                    external_call = client.calls(external_call_sid).fetch()
                    if external_call.status in ['in-progress', 'ringing']:
                        # Terminate the external call
                        hangup_result = client.calls(external_call_sid).update(status='completed')
                except Exception as e:
                    logger.error(f'Failed to terminate external call {external_call_sid}: {e}')

                # Clean up termination context
                try:
                    current_context = call.transfer_context or {}
                    if '_external_termination' in current_context:
                        del current_context['_external_termination']
                        call.transfer_context = current_context
                except Exception as e:
                    logger.error(f'Failed to clean up termination context: {e}')

        except Exception as e:
            logger.error(f'Error handling external call termination: {e}', exc_info=True)

    def transfer(self, to=None):
        self.ensure_one()
        client = self.env['connect.settings'].get_client()
        client.calls(self.sid).update(
            twiml="<Response><Say>Ahoy there</Say></Response>")

    def connect_notify(self, title='Connect', sticky=False, warning=False):
        """Notify user about incoming call.
        """
        caller = self.caller
        caller_avatar = '/web/static/img/placeholder.png'
        if self.partner:
            caller = """
                <p class="text-center"><strong>Partner:</strong>
                <a href='/web#id={}&model={}&view_type=form'>
                    {}
                </a>
                </p>
            """.format(self.partner.id, 'res.partner', self.partner.name)
            caller_avatar = '/web/image/res.partner/{}/image_1024'.format(self.partner.id)
        elif self.caller_user:
            calling_avatar = '/web/image/res.users/{}/image_1024'.format(self.caller_user.id)

        message = """
        <div class="d-flex align-items-center justify-content-center">
            <div>
                <img style="max-height: 100px; max-width: 100px;"
                        class="rounded-circle"
                        src={}/>
            </div>
            <div>
                <p class="text-center">Incoming call</p>
                {}
            </div>
        </div>
        """.format(caller_avatar, caller)

        if release.version_info[0] < 15:
            self.env['bus.bus'].sendone(
                'connect_actions_{}'.format(self.called_user.id),
                {
                    'action': 'notify',
                    'message': message,
                    'title': title,
                    'sticky': sticky,
                    'warning': warning
                })
        else:
            self.env['bus.bus']._sendone(
                'connect_actions_{}'.format(self.called_user.id),
                'connect_notify',
                {
                    'message': message,
                    'title': title,
                    'sticky': sticky,
                    'warning': warning
                })

        return True
