# -*- coding: utf-8 -*

import logging
import time

import hmac

from hashlib import sha256
from odoo.http import request, route, Controller
import json

logger = logging.getLogger(__name__)


class ConnectElevenlabsController(Controller):

    @route('/connect_elevenlabs/agent/call', methods=['POST'], type='http', auth='public', csrf=False)
    def post_call_webhook(self):
        data = json.loads(request.httprequest.get_data(as_text=True)).get('data')

        # headers = request.httprequest.headers.get("elevenlabs-signature")
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
        #     key=request.env['connect.settings'].get_param('elevenlabs_post_call_webhook_secret').encode("utf-8"),
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

        call = request.env['connect.call'].with_user(request.env.ref("connect.user_connect_webhook")).browse(call_id)
        call.write({'elevenlabs_transcription': transcript, 'elevenlabs_summary': transcript_summary})

        return ''
