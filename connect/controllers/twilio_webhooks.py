# -*- coding: utf-8 -*

import logging

from odoo.http import request, Controller, route

logger = logging.getLogger(__name__)


class ConnectController(Controller):

    @staticmethod
    def check_signature(kw):
        kw.update({
            'X-TWILIO-SIGNATURE': request.httprequest.headers.get('X-TWILIO-SIGNATURE', ''),
            'X-TWILIO-WEBHOOK-URL': request.httprequest.url,
        })
        settings = request.env['connect.settings'].with_user(request.env.ref("connect.user_connect_webhook"))
        return settings.check_twilio_request(kw)

    @route('/twilio/webhook/domain', methods=['POST'], type='http', auth='public', csrf=False)
    def domain_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        domain = request.env['connect.domain'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = domain.route_call(kw)
        return f'{res}'

    @route('/twilio/webhook/callstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def callstatus_webhook(self, **kw):
        if not self.check_signature(kw):
            return False
        res = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook")).on_call_status(kw)
        return f'{res}'

    @route('/twilio/webhook/number', methods=['POST'], type='http', auth='public', csrf=False)
    def number_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        res = request.env['connect.number'].with_user(request.env.ref("connect.user_connect_webhook")).route_call(kw)
        return f'{res}'

    @route('/twilio/webhook/outgoing_callerid', methods=['POST'], type='http', auth='public', csrf=False)
    def outgoing_callerid_webhook(self, **kw):
        if not self.check_signature(kw):
            return False
        env = request.env
        outgoing_callerid = env['connect.outgoing_callerid'].with_user(env.ref("connect.user_connect_webhook"))
        res = outgoing_callerid.update_status(kw)
        return f'{res}'

    @route('/twilio/webhook/callflow/<int:flow_id>/gather', methods=['POST'], type='http', auth='public', csrf=False)
    def gather_webhook(self, flow_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        callflow = request.env['connect.callflow'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = callflow.browse(flow_id).gather_action(kw)
        return f'{res}'

    @route('/twilio/webhook/vm_recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def vm_recording_status_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        call = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = call.on_vm_recording_status(kw)
        return f'{res}'

    @route('/twilio/webhook/<string:model_name>/call_action/<int:record_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_edit_webhook(self, model_name, record_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        model = request.env[model_name].with_user(request.env.ref("connect.user_connect_webhook"))
        res = model.on_call_action(record_id, kw)
        return f'{res}'

    @route('/twilio/webhook/recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def recording_status_webhook(self, **kw):
        if not self.check_signature(kw):
            return False
        recording = request.env['connect.recording'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = recording.on_recording_status(kw)
        return f'{res}'

    @route('/twilio/webhook/callaction', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        call = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = call.on_call_action(kw)
        return f'{res}'

    @route('/twilio/webhook/twiml/<int:twiml_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def twiml_webhook(self, twiml_id, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        twiml = request.env['connect.twiml'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = twiml.browse(twiml_id).render(kw)
        return f'{res}'

    @route('/twilio/webhook/message', methods=['POST'], type='http', auth='public', csrf=False)
    def message_webhook(self, **kw):
        if not self.check_signature(kw):
            return '<Response><Say>Invalid Twilio request!</Say></Response>'
        message = request.env['connect.message'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = message.receive(kw)
        return f'{res}'
