# -*- coding: utf-8 -*
import json
import logging

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

    @http.route('/connect_elevenlabs/post_call', methods=['POST'],
                type='http', auth='public', csrf=False)
    def post_call_webhook(self):
        """EL posts the conversation transcript/analysis after a call ends.

        Ingests it into a connect.call + connect.recording so the transcript
        surfaces on the call and downstream hooks (Oduist Memory retain) fire.
        Always 200s so EL does not retry indefinitely on our internal errors.
        """
        logger.info('Incoming request: /connect_elevenlabs/post_call')
        if not self.check_tool_token():
            raise Unauthorized()
        try:
            body = json.loads(http.request.httprequest.get_data(as_text=True) or '{}')
        except Exception as e:
            logger.warning('Post call: bad JSON body: %s', e)
            return ''
        # EL wraps the payload as {"type": "...", "data": {...}}; accept either.
        data = body.get('data') if isinstance(body.get('data'), dict) else body
        try:
            http.request.env['connect.call'].with_user(
                http.request.env.ref('connect.user_connect_webhook')
            ).create_from_elevenlabs_inbound(data)
        except Exception as e:
            logger.exception('Post call ingestion failed: %s', e)
        return ''


