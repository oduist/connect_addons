# -*- coding: utf-8 -*
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging

from odoo import http
from odoo.http import request, Controller, route

logger = logging.getLogger(__name__)


class ConnectPlusController(Controller):

    @route('/twilio/webhook/domain', methods=['POST'], type='http', auth='public', csrf=False)
    def domain_webhook(self, **kw):
        domain = request.env['connect.domain'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = domain.route_call(kw)
        return f'{res}'

    @route('/twilio/webhook/callstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def callstatus_webhook(self, **kw):
        print('-----', request.httprequest.headers)
        res = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook")).on_call_status(kw)
        return f'{res}'

    @route('/twilio/webhook/number', methods=['POST'], type='http', auth='public', csrf=False)
    def number_webhook(self, **kw):
        res = request.env['connect.number'].with_user(request.env.ref("connect.user_connect_webhook")).route_call(kw)
        return f'{res}'

    @route('/twilio/webhook/outgoing_callerid', methods=['POST'], type='http', auth='public', csrf=False)
    def outgoing_callerid_webhook(self, **kw):
        env = request.env
        outgoing_callerid = env['connect.outgoing_callerid'].with_user(env.ref("connect.user_connect_webhook"))
        res = outgoing_callerid.update_status(kw)
        return f'{res}'

    @route('/twilio/webhook/callflow/<int:flow_id>/gather', methods=['POST'], type='http', auth='public',
                csrf=False)
    def gather_webhook(self, flow_id, **kw):
        callflow = request.env['connect.callflow'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = callflow.browse(flow_id).gather_action(kw)
        return f'{res}'

    @route('/twilio/webhook/vm_recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def vm_recording_status_webhook(self, **kw):
        call = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = call.on_vm_recording_status(kw)
        return f'{res}'

    @route('/twilio/webhook/<string:model_name>/call_action/<int:record_id>', methods=['POST'], type='http',
                auth='public', csrf=False)
    def call_action_edit_webhook(self, model_name, record_id, **kw):
        model = request.env[model_name].with_user(request.env.ref("connect.user_connect_webhook"))
        res = model.on_call_action(record_id, kw)
        return f'{res}'

    @route('/twilio/webhook/recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def recording_status_webhook(self, **kw):
        recording = request.env['connect.recording'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = recording.on_recording_status(kw)
        return f'{res}'

    @route('/twilio/webhook/callaction', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_webhook(self, **kw):
        call = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = call.on_call_action(kw)
        return f'{res}'

    @route('/twilio/webhook/calloutstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def callout_status_webhook(self, **kw):
        callout = request.env['connect.callout'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = callout.calloutstatus(kw)
        return f'{res}'

    @route('/twilio/webhook/calloutaction', methods=['POST'], type='http', auth='public', csrf=False)
    def callout_action_webhook(self, **kw):
        callout = request.env['connect.callout'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = callout.on_callout_action(kw)
        return f'{res}'

    @route('/twilio/webhook/twiml/<int:twiml_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def twiml_webhook(self, twiml_id, **kw):
        twiml = request.env['connect.twiml'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = twiml.browse(twiml_id).render(kw)
        return f'{res}'

    @route('/twilio/webhook/queue/<int:q_id>/<string:method>', methods=['POST'], type='http', auth='public',
                csrf=False)
    def queue_webhook(self, q_id, method, **kw):
        queue = getattr(request.env['connect.queue'], method).with_user(request.env.ref("connect.user_connect_webhook"))
        res = queue.browse(q_id)(kw)
        return f'{res}'

    @route('/twilio/webhook/message', methods=['POST'], type='http', auth='public', csrf=False)
    def message_webhook(self, **kw):
        message = request.env['connect.message'].with_user(request.env.ref("connect.user_connect_webhook"))
        res = message.receive(kw)
        return f'{res}'
