# -*- coding: utf-8 -*

import json
import logging
import requests
from odoo import http, SUPERUSER_ID, registry, release
from werkzeug.exceptions import BadRequest, NotFound, Unauthorized
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class ConnectElevenlabsController(http.Controller):

    def check_agent_request(self):
        auth_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        agent_token = http.request.httprequest.headers.get('x-elevenlabs-agent-token')
        if auth_token != agent_token:
            raise Unauthorized('Unauthorized request')

    @http.route('/connect_elevenlabs/transfer', methods=['POST'], type='http', auth='public', csrf=False)
    def transfer_webhook(self):
        self.check_agent_request()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        agent = http.request.env['connect.elevenlabs_agent'].with_user(
            http.request.env.ref("connect.user_connect_webhook")).sudo()
        agent.transfer(data.get('call_sid'))
        return 'Transfered'


    @http.route('/connect_elevenlabs/post_call', methods=['POST'], type='http', auth='public', csrf=False)
    def post_call_webhook(self):
        data = json.loads(http.request.httprequest.get_data(as_text=True)).get('data')

        # headers = http.request.httprequest.headers.get("elevenlabs-signature")
        # if not headers:
        #     return
        # timestamp = headers.split(",")[0][2:]
        # hmac_signature = headers.split(",")[1]
        # # Validate timestamp
        # tolerance = int(time.time()) - 30 * 60
        # if int(timestamp) < tolerance:
        #     return ''
        #
        # # Validate signature
        # full_payload_to_sign = f"{timestamp}.{data}"
        # mac = hmac.new(
        #     key=http.request.env['connect.settings'].get_param('elevenlabs_post_call_webhook_secret').encode("utf-8"),
        #     msg=full_payload_to_sign.encode("utf-8"),
        #     digestmod=sha256,
        # )
        # digest = 'v0=' + mac.hexdigest()
        # if hmac_signature != digest:
        #     return ''
        dynamic_variables = data.get('conversation_initiation_client_data').get('dynamic_variables')
        call_id = int(dynamic_variables.get('call_id'))
        transcript_summary = data.get('analysis').get('transcript_summary')
        transcript_data = data.get('transcript')
        transcript_list = [f"{transcript['role']}: {transcript['message']}" for transcript in transcript_data]
        transcript = '\n'.join(transcript_list)

        call = http.request.env['connect.call'].with_user(http.request.env.ref("connect.user_connect_webhook")).browse(call_id)
        call.write({'elevenlabs_transcription': transcript, 'elevenlabs_summary': transcript_summary})

        return ''
