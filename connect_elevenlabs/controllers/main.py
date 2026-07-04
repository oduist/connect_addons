# -*- coding: utf-8 -*
import base64
import hmac
import json
import logging
import time
from hashlib import sha256

import requests
from werkzeug.exceptions import Unauthorized

from odoo import http

logger = logging.getLogger(__name__)


class ConnectElevenlabsController(http.Controller):

    def dispatch(self, method_name, args, kwargs):
        http.request.env['oduist.license'].check_license('connect_elevenlabs', silent=False)
        return super().dispatch(method_name, args, kwargs)

    def check_tool_token(self):
        token = http.request.httprequest.headers.get('x-elevenlabs-agent-token')
        if not token:
            logger.warning('Tool token check failed: no x-elevenlabs-agent-token header in request')
            return False
        expected_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        if not expected_token:
            logger.warning('Tool token check failed: elevenlabs_agent_token is not configured in settings')
            return False
        if token != expected_token:
            logger.warning('Tool token check failed: token mismatch (received %s...)', token[:8])
            return False
        logger.info('Tool token check passed')
        return True

    def check_post_call_webhook(self):
        payload = http.request.httprequest.get_data(as_text=True)
        headers = http.request.httprequest.headers.get("elevenlabs-signature")
        if not headers:
            logger.warning('Post call webhook check failed: no elevenlabs-signature header')
            return False
        timestamp = headers.split(",")[0][2:]
        hmac_signature = headers.split(",")[1]
        # Validate timestamp
        tolerance = int(time.time()) - 30 * 60
        if int(timestamp) < tolerance:
            logger.info('Invalid elevenlabs post call webhook timestamp!')
            return False
        # Validate signature
        full_payload_to_sign = f"{timestamp}.{payload}"
        webhook_secret = http.request.env['connect.settings'].sudo().get_param('elevenlabs_post_call_webhook_secret')
        mac = hmac.new(
            key=webhook_secret.encode("utf-8"),
            msg=full_payload_to_sign.encode("utf-8"),
            digestmod=sha256,
        )
        digest = 'v0=' + mac.hexdigest()
        if hmac_signature != digest:
            logger.warning('Post call webhook check failed: signature mismatch')
            return False
        logger.info('Post call webhook signature check passed')
        return True

    @http.route('/connect_elevenlabs/transfer', methods=['POST'], type='http', auth='public', csrf=False)
    def transfer_webhook(self):
        logger.info('Incoming request: /connect_elevenlabs/transfer')
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        agent = http.request.env['connect.elevenlabs_agent'].sudo()
        res = agent.transfer(**data)
        return res


    @http.route('/connect_elevenlabs/post_call', methods=['POST'], type='http', auth='public', csrf=False)
    def post_call_webhook(self):
        logger.info('Incoming request: /connect_elevenlabs/post_call')
        if not self.check_post_call_webhook():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True)).get('data')

        dynamic_variables = data.get('conversation_initiation_client_data').get('dynamic_variables')
        call_id = int(dynamic_variables.get('call_id'))
        transcript_summary = data.get('analysis').get('transcript_summary')
        transcript_data = data.get('transcript')
        transcript_list = [f"{transcript['role']}: {transcript['message']}" for transcript in transcript_data]
        transcript = '\n'.join(transcript_list)

        call = http.request.env['connect.call'].sudo().browse(call_id)
        call.write({
            'elevenlabs_summary': transcript_summary,
            'elevenlabs_conversation_id': data.get('conversation_id', '')
        })

        # Recording
        url = f"https://api.elevenlabs.io/v1/convai/conversations/{data.get('conversation_id')}/audio"
        elevenlabs_api_key = http.request.env['connect.settings'].sudo().get_param('elevenlabs_api_key')
        headers = {"Content-Type": "application/json", "xi-api-key": elevenlabs_api_key}

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            audio_data = base64.b64encode(response.content)
            recording = http.request.env['connect.recording'].with_context(skip_transcription=True)
            recording.sudo().create({
                'call': call_id,
                'elevenlabs_transcript': transcript,
                'elevenlabs_summary': transcript_summary,
                'sid': data.get('conversation_id'),
                'call_sid': call.channels[0].sid,
                'start_time': call.create_date,
                'elevenlabs_media_file': audio_data,
                'duration': data['metadata']['call_duration_secs'],
                'caller_number': data['conversation_initiation_client_data']['dynamic_variables']['caller_number'],
                'called_number': data['conversation_initiation_client_data']['dynamic_variables']['called_number'],
                'status': 'completed',
                'partner': call.partner.id,
                'caller_user': call.caller_user.id,
            })
        return ''
