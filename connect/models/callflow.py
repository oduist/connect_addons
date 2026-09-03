# -*- coding: utf-8 -*-

import logging
from datetime import datetime
from urllib.parse import urljoin
from pytz import utc
from odoo import fields, models, api, release
from twilio.twiml.voice_response import Gather, VoiceResponse, Say, Client, Sip, Dial
from .twiml import pretty_xml
from .settings import debug

logger = logging.getLogger(__name__)

class CallflowChoice(models.Model):
    _name = 'connect.callflow_choice'
    _description = 'Callflow Choice'

    callflow = fields.Many2one('connect.callflow', required=True, ondelete='cascade')
    choice_digits = fields.Char(required=True)
    exten = fields.Many2one('connect.exten', ondelete='restrict', required=True)
    speech = fields.Char()


class CallFlow(models.Model):
    _name = 'connect.callflow'
    _description = 'Call Flow'
    _order = 'name asc'

    name = fields.Char(required=True)
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number', store=True)
    language = fields.Char(default='en-US', required=True)
    voice = fields.Char(required=True, default='man')
    gather_input = fields.Boolean()
    gather_input_type = fields.Selection(string='Input Type',
        selection=[
            ('dtmf speech', 'DTMF + speech'),
            ('dtmf', 'DTMF'),
            ('speech', 'Speech')
        ], required=True, default='dtmf speech')
    gather_timeout = fields.Integer(string='Timeout', default=5)
    gather_hints = fields.Char('Hints', default='This is a phrase I expect to hear, department name or extension number')
    prompt_message = fields.Text('Prompt Message',
        default='Welcome to our company! Please enter the extension number of person '
                'you wish to dial or wait 5 seconds till I start connecting your call')
    invalid_input_message = fields.Text(default='We received wrong input. Please try again!')
    gather_digits = fields.Integer(required=True, default=1)
    choices = fields.One2many('connect.callflow_choice', 'callflow')
    gather_action_url = fields.Char(compute='_get_gather_action_url')
    ring_users = fields.Many2many('connect.user')
    ring_timeout = fields.Integer(string='Ring Timeout', default=30,
        help='Number of seconds to ring users before timeout. Default is 30 seconds.')
    record_calls = fields.Boolean()
    ring_contact_manager = fields.Boolean(string='Connect to Manager', default=False)
    ring_contact_manager_timeout = fields.Integer(string='Connect Timeout', default=15, required=True)
    ring_contact_manager_prompt = fields.Text(string='Connect Manager Prompt',
        default='Please wait while I connect you to your account manager...',
        help='If not set the caller will hear a standard ringing tone.')
    calendar = fields.Many2one('resource.calendar', string='Calendar')
    off_calendar_callflow = fields.Many2one('connect.callflow', string='Off Calendar Callflow')
    voicemail_prompt = fields.Text()
    voicemail_enabled = fields.Boolean()
    # fallback_extension

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'callflow')

    def _get_gather_action_url(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        edge = self.env['connect.settings'].get_param('twilio_edge')
        for rec in self:
            rec.gather_action_url = urljoin(api_url,
                'twilio/webhook/callflow/{}/gather#e={}'.format(rec.id, edge))

    @api.model
    def gather_action(self, flow_id, request):
        callflow = self.browse(flow_id)
        choice = callflow.choices.filtered(
            lambda x: x.choice_digits == request.get('Digits') or
                (x.speech and request.get('SpeechResult') and x.speech in
                request.get('SpeechResult', '')))
        if not choice:
            logger.warning('Gather choice digits: %s, speech: %s not found in Call Flow %s',
                request.get('Digits'), request.get('SpeechResult'), callflow.name)
            return callflow.render(request=request, params={'invalid_input': True})
        return choice[0].exten.render(request=request)

    def render(self, request={}, params={}, fallback_effort=0):
        self.ensure_one()
        # If a calendar is set for this call flow, check if the current time is within business hours.
        if self.calendar:
            now_utc = datetime.now(utc)
            end_time = now_utc.replace(hour=23, minute=59, second=59)
            intervals = self.calendar.sudo()._work_intervals_batch(now_utc, end_time)[False]
            is_working_time = any(start <= now_utc < end for start, end, meta in intervals)
            if not is_working_time:
                if self.off_calendar_callflow:
                    debug(self, 'Outside of calendar hours, rendering off-calendar callflow.')
                    return self.off_calendar_callflow.render(request, params, fallback_effort+1)
                else:
                    debug(self, 'Outside of calendar hours, no off-calendar callflow, hanging up.')
                    response = VoiceResponse()
                    response.say('Outside of calendar hours! Goodbye!')
                    response.hangup()
                    return response

        if self.ring_contact_manager and not params.get('no_ring_contact_manager'):
            response = self.render_ring_contact_manager(request, params=params)
            return response

        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].sudo().get_param('twilio_edge')
        voicemail_record_status_url = urljoin(api_url,
                                            'twilio/webhook/vm_recordingstatus?vm_callflow_id={}#e={}'.format(self.id, edge))
        status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
        action_url = urljoin(api_url, 'twilio/webhook/connect.callflow/call_action/{}#e={}'.format(self.id, edge))
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus#e={}'.format(edge))
        refer_url = urljoin(api_url, 'twilio/webhook/sip_refer#e={}'.format(edge))
        invalid_input = params.get('invalid_input')
        response = VoiceResponse()
        if invalid_input:
            self.get_gather_invalid_input_message(response)
        if self.prompt_message and self.gather_input:
            gather = Gather(
                action=self.gather_action_url,
                method='POST',
                timeout=self.gather_timeout,
                numDigits=str(self.gather_digits),
                input=self.gather_input_type,
                language=self.language
            )
            self.get_prompt_message(gather)
            response.append(gather)
        elif self.prompt_message:
            self.get_prompt_message(response)
        # Add ringall users
        if self.ring_users:
            callerId = request.get('Caller')
            # Hack to enable testing callflow from SIP or Client.
            if callerId.startswith('sip:') or callerId.startswith('client:'):
                # Take the default number
                callerId = self.env['connect.outgoing_callerid'].sudo().search(
                    [('is_default', '=', True)], limit=1).number
                if not callerId:
                    response = VoiceResponse()
                    response.say('Your must configure a default number for caller ID!')
                    return response
            if self.record_calls:
                dial = Dial(callerId=callerId, action=action_url, timeout=self.ring_timeout,
                        record='record-from-answer-dual', recordingStatusCallback=record_status_url,
                        referUrl=refer_url)
            else:
                dial = Dial(callerId=callerId, action=action_url, timeout=self.ring_timeout,
                        referUrl=refer_url)
            # Resolve the caller's contact name + partner id for the client legs,
            # mirroring user.render_client, so a ring-group call shows the contact
            # name/avatar and a clickable partner instead of the raw number. Fall
            # back to a caller-number lookup for the inbound-DID case where the
            # channel isn't linked to the partner at render time.
            channel = self.env['connect.channel'].sudo().search(
                [('sid', '=', request.get('CallSid'))], limit=1)
            call = channel.call if channel else None
            raw_caller = request.get('Caller') or ''
            if call and call.partner:
                caller_partner = call.partner
            elif channel and channel.caller_user:
                caller_partner = channel.caller_user.partner_id
            elif raw_caller.startswith('+'):
                caller_partner = self.env['res.partner'].sudo().get_partner_by_number(raw_caller)
            else:
                caller_partner = self.env['res.partner']
            caller_partner_id = caller_partner.id if caller_partner else False
            caller_name = caller_partner.name if caller_partner else False
            for user in self.ring_users:
                callflows = self.env['connect.user_callflow'].sudo().search(
                    [('callflow_type', 'in', ['sip', 'client']), ('user', '=', user.id)], order='prio')
                for callflow in callflows:
                    if callflow.callflow_type == 'sip':
                        dial.sip('sip:{}'.format(user.uri),
                                statusCallbackEvent='answered completed',
                                statusCallback=status_url)
                    else:
                        client = Client(
                            statusCallbackEvent='answered completed',
                            statusCallback=status_url)
                        client.identity(user.get_client_identity())
                        if caller_name:
                            client.parameter(name='CallerName', value=caller_name)
                        client.parameter(name='Partner', value=caller_partner_id)
                        dial.append(client)
            response.append(dial)
        else:
            # No ring users set, just send to voicemail if enabled.
            if self.voicemail_enabled and self.voicemail_prompt:
                response.pause(length=1)
                self.get_voicemail_prompt_message(response)
                response.record(
                    maxLength=120,
                    finishOnKey='#',
                    playBeep=True,
                    recordingStatusCallback=voicemail_record_status_url)
            else:
                # No voicemail, just say sorry and hangup.
                response.say('This callflow has no actions! Goodbye!')
                response.pause(length=1)
                response.hangup()
        debug(self, pretty_xml(str(response)))
        return response

    def get_prompt_message(self, response):
        debug(self, 'Saying prompt message for Call Flow {}'.format(self.name))
        response.say(self.prompt_message, language=self.language, voice=self.voice)

    def get_gather_invalid_input_message(self, response):
        response.say(self.invalid_input_message, language=self.language, voice=self.voice)

    def get_voicemail_prompt_message(self, response):
        response.say(self.voicemail_prompt, language=self.language, voice=self.voice)

    def render_ring_contact_manager(self, request, params={}):
        self.ensure_one()
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        action_url = urljoin(api_url, 'twilio/webhook/connect_callflow_ring_contact_manager_action/{}'.format(self.id))
        response = VoiceResponse()
        # Check the partner by number
        partner = self.env['res.partner'].get_partner_by_number(request['Caller'])
        params.update({'no_ring_contact_manager': True})
        if not (partner and partner.user_id):
            debug(self, 'Contact Manager for number {} not found.'.format(request['Caller']))
            return self.render(request, params)
        else:
            debug(self, 'Found partner {}[{}] for number {}.'.format(partner.name, partner.id, request['Caller']))
        # Check partner's PBX user.
        connect_user = partner.user_id.connect_user
        if not connect_user:
            debug(self, 'Connect User for Sale Manager {}[{}] is not configured.'.format(
                partner.user_id.name, partner.user_id.id))
            return self.render(request, params)
        # Render connect user
        debug(self, 'Connect caller to Manager {}[{}].'.format(partner.user_id.name, partner.user_id.id))
        return connect_user.render(request, params={'dial_action_url': action_url})

    def on_ring_contact_manager_action(self, flow_id, request):
        if request['DialCallStatus'] != 'completed':
            debug(self, 'Contact Manager dial status: {}, fallback on the callflow.'.format(request['DialCallStatus']))
            return self.browse(flow_id).render(request, params={'no_ring_contact_manager': True})
        else:
            debug(self, 'Contact Manager successfully answered the call. Hangup.')
            response = VoiceResponse()
            response.hangup()
            return response

    @api.model
    def on_call_action(self, flow_id, request):
        response = VoiceResponse()
        if request.get('DialCallStatus') != 'completed':
            callflow = self.browse(flow_id)
            # The call was not connected, point to the voicemail
            if callflow.voicemail_prompt:
                api_url = self.env['connect.settings'].sudo().get_param('api_url')
                edge = self.env['connect.settings'].sudo().get_param('twilio_edge')
                record_status_url = urljoin(
                    api_url, 'twilio/webhook/vm_recordingstatus?vm_callflow_id={}#e={}'.format(callflow.id, edge))
                response.pause(length=1)
                callflow.get_voicemail_prompt_message(response)
                response.record(
                    maxLength=120,
                    finishOnKey='#',
                    playBeep=True,
                    recordingStatusCallback=record_status_url)
            else:
                # No voicemail, just say sorry and hangup.
                response.say('Sorry, I could not connect your call. Goodbye!')
                response.pause(length=1)
                response.hangup()
        else:
            # Call was connected, just hangup if the call was hangup by
            # the called party and the caller is still here.
            response.hangup()
        debug(self, pretty_xml(str(response)))
        return response
