# -*- coding: utf-8 -*
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging

from odoo import http

logger = logging.getLogger(__name__)


class ConnectPlusController(http.Controller):

    @http.route('/twilio/webhook/domain', methods=['POST'], type='http', auth='public', csrf=False)
    def domain_webhook(self, **kw):
        res = http.request.env['connect.domain'].route_call(kw)
        return f'{res}'

    @http.route('/twilio/webhook/callstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def callstatus_webhook(self, **kw):
        res = http.request.env['connect.call'].on_call_status(kw)
        return f'{res}'

    @http.route('/twilio/webhook/number', methods=['POST'], type='http', auth='public', csrf=False)
    def number_webhook(self, **kw):
        res = http.request.env['connect.number'].route_call(kw)
        return f'{res}'

    @http.route('/twilio/webhook/outgoing_callerid', methods=['POST'], type='http', auth='public', csrf=False)
    def outgoing_callerid_webhook(self, **kw):
        res = http.request.env['connect.outgoing_callerid'].update_status(kw)
        return f'{res}'

    @http.route('/twilio/webhook/callflow/<int:flow_id>/gather', methods=['POST'], type='http', auth='public', csrf=False)
    def gather_webhook(self, flow_id, **kw):
        res = http.request.env['connect.callflow'].browse(flow_id).gather_action(kw)
        return f'{res}'

    @http.route('/twilio/webhook/vm_recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def vm_recording_status_webhook(self, **kw):
        res = http.request.env['connect.call'].on_vm_recording_status(kw)
        return f'{res}'

    @http.route('/twilio/webhook/<string:model_name>/call_action/<int:record_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_edit_webhook(self, model_name, record_id, **kw):
        res = http.request.env[model_name].sudo().on_call_action(record_id, kw)
        return f'{res}'

    @http.route('/twilio/webhook/recordingstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def recording_status_webhook(self, **kw):
        res = http.request.env['connect.recording'].on_recording_status(kw)
        return f'{res}'

    @http.route('/twilio/webhook/callaction', methods=['POST'], type='http', auth='public', csrf=False)
    def call_action_webhook(self, **kw):
        res = http.request.env['connect.call'].on_call_action(kw)
        return f'{res}'

    @http.route('/twilio/webhook/calloutstatus', methods=['POST'], type='http', auth='public', csrf=False)
    def callout_status_webhook(self, **kw):
        res = http.request.env['connect.callout'].calloutstatus(kw)
        return f'{res}'

    @http.route('/twilio/webhook/calloutaction', methods=['POST'], type='http', auth='public', csrf=False)
    def callout_action_webhook(self, **kw):
        res = http.request.env['connect.callout'].on_callout_action(kw)
        return f'{res}'

    @http.route('/twilio/webhook/twiml/<int:twiml_id>', methods=['POST'], type='http', auth='public', csrf=False)
    def twiml_webhook(self, twiml_id, **kw):
        res = http.request.env['connect.twiml'].browse(twiml_id).render(kw)
        return f'{res}'

    @http.route('/twilio/webhook/queue/<int:q_id>/<string:method>', methods=['POST'], type='http', auth='public', csrf=False)
    def queue_webhook(self, q_id, method, **kw):
        res = getattr(http.request.env['connect.queue'], method).browse(q_id)(kw)
        return f'{res}'

    @http.route('/twilio/webhook/message', methods=['POST'], type='http', auth='public', csrf=False)
    def message_webhook(self, **kw):
        res = http.request.env['connect.message'].receive(kw)
        return f'{res}'
