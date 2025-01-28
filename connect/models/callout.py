# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import json
import logging
from urllib.parse import urljoin
from odoo import fields, models, api, release
from .settings import strip_number, debug
from twilio.twiml.voice_response import Gather, VoiceResponse, Say, Hangup

logger = logging.getLogger(__name__)


class CalloutLog(models.Model):
    _name = 'connect.callout_log'
    _description = 'Callout Log'
    _order = 'id desc'

    callout = fields.Many2one('connect.callout', required=True, ondelete='cascade')
    message = fields.Text(required=True)


class CallOutChoice(models.Model):
    _name = 'connect.callout_choice'
    _description = 'Callout Choice'

    callout = fields.Many2one('connect.callout', required=True, ondelete='cascade')
    choice_digits = fields.Char(required=True)
    twiml = fields.Many2one('connect.twiml')
    stop = fields.Boolean()
    skip = fields.Boolean()
    speech = fields.Char()


class CalloutContact(models.Model):
    _name = 'connect.callout_contact'
    _description = 'Callout Contact'
    _order = 'id'

    callout = fields.Many2one('connect.callout', required=True, ondelete='cascade')
    partner = fields.Many2one('res.partner', ondelete='set null')
    phone_number = fields.Char(required=True)
    status = fields.Char(default='queued', required=True)
    call_sid = fields.Char(readonly=True)
    choice_digits = fields.Char(readonly=True)
    call_duration = fields.Integer(readonly=True)
    dial_attempts = fields.Integer(required=True, default=1)
    current_attempt = fields.Integer(required=True, default=0)
    skip = fields.Boolean()
    validate_answer = fields.Boolean()
    error_message = fields.Char('Error', readonly=True)
    ref_model = fields.Char()
    ref_res_id = fields.Integer()
    done_status = fields.Boolean(compute='_get_done_status')

    def _get_done_status(self):
        DONE_STATUSES = [
            'completed', 'busy', 'no-answer', 'canceled', 'failed'
        ]
        for rec in self:
            rec.done_status = rec.status in DONE_STATUSES


class CallOut(models.Model):
    _name = 'connect.callout'
    _description = 'Callout'

    name = fields.Char(required=True)
    dial_timeout = fields.Integer(required=True, default=30)
    log_model = fields.Char()
    log_res_id = fields.Integer()
    logs = fields.One2many('connect.callout_log', 'callout')
    status = fields.Selection(
        selection=[
            ('draft', 'Draft'), ('running', 'Running'), ('paused', 'Paused'),
            ('cancelled', 'Cancelled'), ('done', 'Done')],
        required=True, default='draft',
    )
    callerid_number = fields.Many2one('connect.number') # TODO: Remove after 1.0 release
    outgoing_callerid = fields.Many2one('connect.outgoing_callerid', ondelete='restrict',
        domain=['|',('status', '=', 'validated'),('callerid_type', '=', 'number')])
    gather_input = fields.Boolean()
    gather_input_type = fields.Selection(string='Input Type',
        selection=[
            ('dtmf speech', 'DTMF + speech'),
            ('dtmf', 'DTMF'),
            ('speech', 'Speech')
        ], required=True, default='dtmf')
    gather_timeout = fields.Integer(default=5)
    gather_hints = fields.Char('Hints', default='This is a phrase I expect to hear, department name or extension number')
    prompt_message = fields.Text('Prompt Message')
    invalid_input_message = fields.Text(default='We received wrong input. Please try again!')
    after_choice_message = fields.Text(default='Thank you for your input! Good bye!')
    gather_digits = fields.Integer(required=True, default=1)
    choices = fields.One2many('connect.callout_choice', 'callout')
    contacts = fields.One2many('connect.callout_contact', 'callout')
    test_to = fields.Char('Test number')
    active = fields.Boolean(default=True)

    def get_next_contact(self):
        self.ensure_one()
        contacts = self.env['connect.callout_contact'].sudo().search([
            ('callout', '=', self.id),
            ('status', '!=', 'completed'),
            ('skip', '=', False)
        ])
        # Filter contacts by number of dial attempts
        contacts = contacts.filtered(lambda x: x.current_attempt < x.dial_attempts)
        if len(contacts) > 0:
            return contacts[0]
        else:
            # Return empty set
            self.sudo().create_log_message('No more contacts to dial.')
            self.status = 'done'
            return self.env['connect.callout_contact']

    def run(self):
        self.ensure_one()
        contact = self.get_next_contact()
        if contact:
            self.status = 'running'
            self.originate_call(contact)
        else:
            self.status = 'done'

    def pause(self):
        self.ensure_one()
        self.status = 'paused'

    def reset(self):
        self.ensure_one()
        self.status = 'draft'
        self.contacts.write({
            'current_attempt': 0,
            'choice_digits': '',
            'error_message': '',
            'call_duration': 0,
            'skip': False,
            'status': 'queued',
        })
        self.sudo().logs.unlink()

    def cancel(self):
        self.ensure_one()

    def create_log_message(self, message):
        self.ensure_one()
        callout = self
        self.env['connect.callout_log'].create({
            'callout': callout.id,
            'message': message
        })
        # Log to chatter of the target model
        if callout.log_model and callout.log_res_id:
            try:
                record = self.env[callout.log_model].browse(callout.log_res_id)
                record.with_context(tracking_disable=True).message_post(body=message)
            except Exception:
                logger.exception('Log to model %s record ID %s failed:',
                                callout.log_model, callout.log_res_id)

    def render(self, request={}, params={}):
        self.ensure_one()
        get_param = self.env['connect.settings'].sudo().get_param
        gather_action_url = urljoin(get_param('api_url'),
            'twilio/webhook/{}/calloutaction'.format(get_param('instance_uid')))
        response = VoiceResponse()
        gather = Gather(
            action=gather_action_url,
            method='POST',
            numDigits=str(self.gather_digits),
            input=self.gather_input_type,
            actionOnEmptyResult=True,
            timeout=self.gather_timeout,
        )
        self.get_prompt_message(gather)
        response.append(gather)
        return response

    def originate_call(self, contact):
        self.ensure_one()
        number = strip_number(contact.phone_number)
        client = self.env['connect.settings'].get_client()
        get_param = self.env['connect.settings'].sudo().get_param
        callerId = self.outgoing_callerid.number or self.env['connect.outgoing_callerid'].search(
            [('is_default', '=', True)], limit=1).number
        if not callerId:
            self.sudo().create_log_message(
                'Callout CallerID number not set / Default CallerID number not set.')
            return False
        api_url = get_param('api_url')
        instance_uid = get_param('instance_uid', '')
        status_url = urljoin(api_url, 'twilio/webhook/{}/calloutstatus'.format(instance_uid))
        # Check if it has a test number.
        if self.test_to:
            number = self.test_to
        call = client.calls.create(
            timeout=self.dial_timeout,
            twiml=self.render(),
            to=number,
            from_=callerId,
            status_callback=status_url,
            # record=record, recording_channels='dual',
            status_callback_event=['answered', 'completed'],
            status_callback_method='POST'
        )
        contact.write({
            'call_sid': call.sid,
            'current_attempt': contact.current_attempt + 1,
        })

    @api.model
    def on_callout_status(self, params):
        # Check access only for Twilio Service agent.
        if not self.env.user.has_group('connect.group_connect_billing'):
            logger.error('Access to Twilio webhook is denied!')
            return False
        # Check Twilio request
        if not self.env['connect.settings'].check_twilio_request(params):
            return False
        debug(self, 'On callout status: %s' % json.dumps(params, indent=2))
        contact = self.env['connect.callout_contact'].sudo().search([('call_sid', '=', params.get('CallSid'))])
        if not contact:
            logger.error('Cannot find contact by call sid: %s', params.get('CallSid'))
            return False
        callout = contact.callout
        data = {
            'status': params.get('CallStatus'),
            'call_duration': params.get('CallDuration'),
            'error_message': params.get('ErrorMessage'),
        }
        # Check if the contact had not-validated status and keep it.
        if contact.status == 'not-validated':
            data['status'] = 'not-validated'
        contact.write(data)
        callout.create_log_message(
            'Number: {} CallStatus: {}'.format(
                contact.phone_number, params.get('CallStatus'))
        )
        # Check if we have more contacts to dial
        if params.get('CallStatus') in ['busy', 'completed', 'no-answer']:
            if callout.status == 'running':
                next_contact = callout.get_next_contact()
                if next_contact:
                    callout.originate_call(next_contact)
        self.env['connect.settings'].connect_reload_view('connect.callout')
        return True

    @api.model
    def on_callout_action(self, params):
        # Check access only for Twilio Service agent.
        if not self.env.user.has_group('connect.group_connect_billing'):
            logger.error('Access to Twilio webhook is denied!')
            return '<Response><Say>Access to Twilio webhook is denied!</Say></Response>'
        # Check Twilio request
        if not self.env['connect.settings'].check_twilio_request(params):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        debug(self, 'On callout action: %s' % json.dumps(params, indent=2))
        contact = self.env['connect.callout_contact'].sudo().search([('call_sid', '=', params.get('CallSid'))])
        response = VoiceResponse()
        if contact.callout.after_choice_message:
            contact.callout.get_after_choice_message(response)
        response.hangup()
        if not contact:
            logger.error('Cannot find contact by call sid: %s', params.get('CallSid'))
            return response
        contact.choice_digits = params.get('Digits')
        contact.callout.sudo().create_log_message(
            'Number: {} ChoiceDigits: {}'.format(
                contact.phone_number, params.get('Digits'))
        )
        # Check if this is a stop choice.
        stop_choices = contact.callout.choices.filtered(lambda x: x.stop == True).mapped('choice_digits')
        if params.get('Digits') and params.get('Digits') in stop_choices:
            contact.callout.sudo().create_log_message(
                'Contact number {} made a stop choice'.format(contact.phone_number))
            debug(self, 'Contact choice %s made stop of callout.' % params.get('Digits'))
            contact.callout.status = 'done'
        # Check if this is a skip choice.
        skip_choices = contact.callout.choices.filtered(lambda x: x.skip == True).mapped('choice_digits')
        if params.get('Digits') and params.get('Digits') in skip_choices:
            contact.callout.sudo().create_log_message(
                'Contact number {} made a skip choice'.format(contact.phone_number))
            debug(self, 'Contact choice %s made a skip.' % params.get('Digits'))
            contact.skip = True
        # Call TwiML
        choice = contact.callout.choices.filtered(lambda x: x.choice_digits == params.get('Digits'))
        if choice and choice.twiml:
            try:
                return choice.twiml.render(
                    request=params, params={
                        'contact': contact,
                    }
                )
            except Exception as e:
                logger.exception('TwiML choice error:')
                response = VoiceResponse()
                response.say('Choice application error, please contact technical support!')
                return response
        # Check if there was no choice but validate answer is set.
        if not params.get('Digits') and contact.validate_answer:
            # Reset contact status to not validated.
            contact.status = 'not-validated'
        elif params.get('Digits') and contact.status == 'not-validated':
            # Reset last call status.
            contact.status = 'received-input'
        return response

    def get_prompt_message(self, gather):
        debug(self, 'Saying prompt message for CallOut {}'.format(self.name))
        gather.say(self.prompt_message.format(gather_timeout=self.gather_timeout))

    def get_after_choice_message(self, response):
        debug(self, 'Saying after choice message for CallOut {}'.format(self.name))
        response.say(self.after_choice_message)

    def get_invalid_input_message(self, response):
        debug(self, 'Saying invalid input message for CallOut {}'.format(self.name))
        response.say(self.invalid_input_message)
