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
        agent = http.request.env['connect.elevenlabs_agent'].with_user(
            http.request.env.ref("connect.user_connect_webhook")).sudo()
        res = agent.transfer(**data)
        return res

    @http.route('/connect_elevenlabs/conversation_initiation', methods=['POST'],
                type='http', auth='public', csrf=False)
    def conversation_initiation_webhook(self):
        """EL fetches per-call context before opening the conversation.

        Always returns a valid JSON envelope — any internal error becomes an
        empty-vars response so EL doesn't kill the call.
        """
        logger.info('Incoming request: /connect_elevenlabs/conversation_initiation')
        if not self.check_tool_token():
            raise Unauthorized()
        try:
            data = json.loads(http.request.httprequest.get_data(as_text=True) or '{}')
        except Exception as e:
            logger.warning('Conversation initiation: bad JSON body: %s', e)
            data = {}
        try:
            payload = http.request.env['connect.elevenlabs_agent'].sudo().build_initiation_payload(
                caller=data.get('caller_id') or '',
                called=data.get('called_number') or '',
                agent_uid=data.get('agent_id') or '',
                call_sid=data.get('call_sid') or '',
            )
        except Exception as e:
            logger.exception('Conversation initiation payload build failed: %s', e)
            payload = {"type": "conversation_initiation_client_data",
                       "dynamic_variables": {}}
        return json.dumps(payload)


    def _create_el_recording(self, call, data, transcript, summary, user):
        conversation_id = data.get('conversation_id')
        if conversation_id:
            existing = http.request.env['connect.recording'].sudo().search(
                [('sid', '=', conversation_id)], limit=1)
            if existing:
                logger.info('EL recording already exists for conversation_id=%s, skipping', conversation_id)
                return existing
        url = f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}/audio"
        elevenlabs_api_key = http.request.env['connect.settings'].sudo().get_param('elevenlabs_api_key')
        response = requests.get(url, headers={"Content-Type": "application/json", "xi-api-key": elevenlabs_api_key})
        if response.status_code != 200:
            logger.warning('Failed to fetch EL recording for conversation %s: HTTP %s', conversation_id, response.status_code)
            return False
        meta = data.get('metadata', {})
        phone_call = meta.get('phone_call', {})
        dyn = data.get('conversation_initiation_client_data', {}).get('dynamic_variables', {})
        caller_number = dyn.get('caller_number') or phone_call.get('external_number', '')
        called_number = dyn.get('called_number') or phone_call.get('agent_number', '')
        call_sid = (call.channels[:1].sid if call.channels else '') or phone_call.get('call_sid', '')
        return http.request.env['connect.recording'].with_context(skip_transcription=True).with_user(user).sudo().create({
            'call': call.id,
            'elevenlabs_transcript': transcript,
            'elevenlabs_summary': summary,
            'sid': conversation_id,
            'call_sid': call_sid,
            'start_time': call.create_date,
            'elevenlabs_media_file': base64.b64encode(response.content),
            'duration': meta.get('call_duration_secs', 0),
            'caller_number': caller_number,
            'called_number': called_number,
            'status': 'completed',
            'partner': call.partner.id if call.partner else False,
            'caller_user': call.caller_user.id if call.caller_user else False,
        })

    @http.route('/connect_elevenlabs/post_call', methods=['POST'], type='http', auth='public', csrf=False)
    def post_call_webhook(self):
        logger.info('Incoming request: /connect_elevenlabs/post_call')
        if not self.check_post_call_webhook():
            raise Unauthorized()
        user_connect_webhook = http.request.env.ref("connect.user_connect_webhook")
        data = json.loads(http.request.httprequest.get_data(as_text=True)).get('data')

        transcript_summary = data.get('analysis', {}).get('transcript_summary', '')
        transcript = '\n'.join(f"{t['role']}: {t['message']}" for t in (data.get('transcript') or []))
        dynamic_variables = data.get('conversation_initiation_client_data', {}).get('dynamic_variables', {})
        legacy_call_id = dynamic_variables.get('call_id')

        if legacy_call_id:
            call = http.request.env['connect.call'].with_user(user_connect_webhook).browse(int(legacy_call_id))
            call.write({
                'elevenlabs_summary': transcript_summary,
                'elevenlabs_conversation_id': data.get('conversation_id', ''),
            })
        else:
            call = http.request.env['connect.call'].with_user(user_connect_webhook).sudo().create_from_elevenlabs_inbound(data)
            if not call:
                logger.error('EL inbound: failed to create connect.call for conversation %s', data.get('conversation_id'))
                return ''

        self._create_el_recording(call, data, transcript, transcript_summary, user_connect_webhook)
        return ''
