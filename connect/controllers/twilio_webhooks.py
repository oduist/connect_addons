# -*- coding: utf-8 -*

import logging

from odoo.http import request, Controller, route, Response
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


class ConnectController(Controller):

    @staticmethod
    def check_signature(data, region=True):
        settings = request.env['connect.settings'].sudo()
        if region:
            auth_token = settings.get_param('region_auth_token') or settings.get_param('auth_token')
        else:
            auth_token = settings.get_param('auth_token')
        validator = RequestValidator(auth_token)
        url = request.httprequest.url.replace('http:', 'https:')
        signature = request.httprequest.headers.get('X-Twilio-Signature', '')
        request_valid = validator.validate(url, data, signature)
        if not request_valid:
            if request.httprequest.url.startswith('http:'):
                logger.error('Twilio requires HTTPS to be setup!')
            else:
                logger.error('Twilio request is not valid!')
        return request_valid

    @route('/twilio/webhook/domain', methods=['POST'], type='http', auth='public', csrf=False)
    def domain_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        domain = request.env['connect.domain'].sudo()
        res = domain.route_call(kw)
        return f'{res}'

    @route('/twilio/webhook/callstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def callstatus_webhook(self, **kw):
        if not self.check_signature(kw):
            return Response("Twilio request is not valid!", status=500)
        res = request.env['connect.call'].sudo().on_call_status(kw)
        return f'{res}'

    @route('/twilio/webhook/number', methods=['POST'], type='http', auth='public', csrf=False)
    def number_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        res = request.env['connect.number'].sudo().route_call(kw)
        return f'{res}'

    @route('/twilio/webhook/outgoing_callerid', methods=['POST'], type='http', auth='public', csrf=False)
    def outgoing_callerid_webhook(self, **kw):
        if not self.check_signature(kw):
            return Response("Twilio request is not valid!", status=500)
        outgoing_callerid = request.env['connect.outgoing_callerid'].sudo()
        res = outgoing_callerid.update_status(kw)
        return f'{res}'

    @route('/twilio/webhook/callflow/<int:flow_id>/gather', methods=['POST'], type='http', auth='public', csrf=False)
    def gather_webhook(self, flow_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        callflow = request.env['connect.callflow'].sudo()
        res = callflow.gather_action(flow_id, kw)
        return f'{res}'

    @route('/twilio/webhook/vm_recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def vm_recording_status_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        call = request.env['connect.call'].sudo()
        res = call.on_vm_recording_status(kw)
        return f'{res}'

    @route('/twilio/webhook/<string:model_name>/call_action/<int:record_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_edit_webhook(self, model_name, record_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        model = request.env[model_name].sudo()
        res = model.on_call_action(record_id, kw)
        return f'{res}'

    @route('/twilio/webhook/recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def recording_status_webhook(self, **kw):
        if not self.check_signature(kw):
            return Response("Twilio request is not valid!", status=500)
        recording = request.env['connect.recording'].sudo()
        res = recording.on_recording_status(kw)
        return f'{res}'

    @route('/twilio/webhook/callaction', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        call = request.env['connect.call'].sudo()
        res = call.on_call_action(kw)
        return f'{res}'

    @route('/twilio/webhook/twiml/<int:twiml_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def twiml_webhook(self, twiml_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        twiml = request.env['connect.twiml'].sudo()
        res = twiml.browse(twiml_id).render(kw)
        return f'{res}'

    @route('/twilio/webhook/message', methods=['POST'], type='http', auth='public', csrf=False)
    def message_webhook(self, **kw):
        if not self.check_signature(kw, region=False):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        message = request.env['connect.message'].sudo()
        res = message.receive(kw)
        return f'{res}'

    @route('/twilio/webhook/message_status', methods=['POST'], type='http', auth='public', csrf=False)
    def message_status_webhook(self, **kw):
        if not self.check_signature(kw, region=False):
            return Response("Twilio request is not valid!", status=500)
        request.env['connect.message'].sudo().update_message_status(kw)
        return 'OK'

    @route('/twilio/webhook/whatsapp_message_status', methods=['POST'], type='http', auth='public', csrf=False)
    def whatsapp_message_status_webhook(self, **kw):
        if not self.check_signature(kw, region=False):
            return Response("Twilio request is not valid!", status=500)
        request.env['connect.whatsapp_sender'].sudo().update_message_status(kw)
        return 'OK'

    @route('/twilio/webhook/connect_callflow_ring_contact_manager_action/<int:record_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def callflow_ring_contact_manager_action(self, record_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        model = request.env['connect.callflow'].sudo()
        res = model.on_ring_contact_manager_action(record_id, kw)
        return f'{res}'

    @route('/twilio/webhook/sip_refer', methods=['POST'], type='http', auth='public', csrf=False)
    def sip_refer_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        res = request.env['connect.user'].sudo().handle_sip_refer(kw)
        return f'{res}'

    @route('/twilio/webhook/transfer_continuation', methods=['POST'], type='http', auth='public', csrf=False)
    def transfer_continuation_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        transfer_wizard = request.env['connect.transfer_wizard'].sudo()
        res = transfer_wizard.handle_transfer_continuation(kw)
        return f'{res}'
