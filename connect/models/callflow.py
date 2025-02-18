# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging
from urllib.parse import urljoin
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
    voice = fields.Char(required=True, default='Woman')
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
    record_calls = fields.Boolean()
    voicemail_prompt = fields.Text()
    voicemail_enabled = fields.Boolean()
    # fallback_extension

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'callflow')

    def _get_gather_action_url(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        for rec in self:
            rec.gather_action_url = urljoin(api_url, 'twilio/webhook/callflow/{}/gather'.format(rec.id))

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

    def render(self, request={}, params={}):
        self.ensure_one()
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        voicemail_record_status_url = urljoin(api_url, 'twilio/webhook/vm_recordingstatus')
        status_url = urljoin(api_url, 'twilio/webhook/callstatus')
        action_url = urljoin(api_url, 'twilio/webhook/connect.callflow/call_action/{}'.format(self.id))
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus')
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
            callerId = request.get('From')
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
                dial = Dial(callerId=callerId, action=action_url,
                        record='record-from-answer-dual', recordingStatusCallback=record_status_url)
            else:
                dial = Dial(callerId=callerId, action=action_url)
            for user in self.ring_users:
                if user.ring_first == 'sip':
                    dial.sip('sip:{}'.format(user.uri),
                            statusCallbackEvent='answered completed',
                            statusCallback=status_url)
                elif user.ring_first == 'client':
                    client = Client(
                        statusCallbackEvent='answered completed',
                        statusCallback=status_url)
                    client.identity(user.uri)
                    client.parameter(name='CallerName', value=callerId)
                    dial.append(client)
                # Ring 2nd
                if user.ring_second == 'sip':
                    dial.sip('sip:{}'.format(user.uri),
                            statusCallbackEvent='answered completed',
                            statusCallback=status_url)
                elif user.ring_second == 'client':
                    client = Client(
                        statusCallbackEvent='answered completed',
                        statusCallback=status_url)
                    client.identity(user.uri)
                    client.parameter(name='CallerName', value=callerId)
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

    @api.model
    def on_call_action(self, flow_id, request):
        response = VoiceResponse()
        if request.get('DialCallStatus') != 'completed':
            callflow = self.browse(flow_id)
            # The call was not connected, point to the voicemail
            if callflow.voicemail_prompt:
                api_url = self.env['connect.settings'].sudo().get_param('api_url')
                record_status_url = urljoin(api_url, 'twilio/webhook/vm_recordingstatus')
                response.pause(length=1)
                response.say(callflow.voicemail_prompt, language=callflow.language, voice=callflow.voice)
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
