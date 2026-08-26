# -*- coding: utf-8 -*
import hashlib
import hmac
import json
import logging
import time

from werkzeug.exceptions import Unauthorized

from odoo import http

logger = logging.getLogger(__name__)

# Reject post-call deliveries whose signed timestamp is older than this (anti-replay).
POST_CALL_MAX_SKEW_SECS = 30 * 60


class ConnectElevenlabsController(http.Controller):

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

    def _verify_post_call_signature(self, raw_body):
        """Verify EL's ElevenLabs-Signature HMAC over the post-call body.

        Header format: ``t=<unix_ts>,v0=<hex_hmac_sha256>`` where the signed
        message is ``"<t>.<raw_body>"`` and the key is the webhook secret we
        stored when creating the webhook entity.
        """
        secret = http.request.env['connect.settings'].sudo().get_param(
            'elevenlabs_post_call_webhook_secret')
        if not secret:
            logger.warning('Post call: no webhook secret configured; run ElevenLabs sync')
            return False
        sig = http.request.httprequest.headers.get('ElevenLabs-Signature') or ''
        parts = dict(p.split('=', 1) for p in sig.split(',') if '=' in p)
        ts, v0 = parts.get('t'), parts.get('v0')
        if not ts or not v0:
            logger.warning('Post call: missing ElevenLabs-Signature header')
            return False
        try:
            if abs(time.time() - int(ts)) > POST_CALL_MAX_SKEW_SECS:
                logger.warning('Post call: signature timestamp out of tolerance')
                return False
        except ValueError:
            return False
        expected = hmac.new(
            secret.encode(), f'{ts}.{raw_body}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v0):
            logger.warning('Post call: HMAC signature mismatch')
            return False
        return True

    @http.route('/connect_elevenlabs/create_partner', methods=['POST'], type='http',
                auth='public', csrf=False)
    def create_partner(self):
        logger.info('Incoming request: /connect_elevenlabs/create_partner')
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent data: %s', data)
        call = http.request.env['connect.call'].sudo().browse(int(data['call_id']))
        if call.direction == 'outgoing':
            data['partner_phone'] = call.called
        else:
            data['partner_phone'] = call.caller
        partner = http.request.env['res.partner'].sudo().with_context(
            connect_call_id=int(data['call_id'])).create({
                'name': data['name'],
                'phone': data.get('partner_phone')
            })
        logger.info('Partner %s (%s) has been created: ', partner.name, partner.id)
        # Now assign partner to the call.
        call.partner = partner.id
        return http.request.make_json_response({
            'partner_id': partner.id,
            'message': 'Partner created'
        })

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
            sip_headers = data.get('sip_headers') or {}
            payload = http.request.env['connect.elevenlabs_agent'].sudo().build_initiation_payload(
                caller=data.get('caller_id') or '',
                called=data.get('called_number') or '',
                agent_uid=data.get('agent_id') or '',
                call_sid=data.get('call_sid') or '',
                call_ref=sip_headers.get('X-Connect-Call-Ref') or '',
            )
        except Exception as e:
            logger.exception('Conversation initiation payload build failed: %s', e)
            payload = {"type": "conversation_initiation_client_data",
                       "dynamic_variables": {}}
        return json.dumps(payload)

    @http.route('/connect_elevenlabs/post_call', methods=['POST'],
                type='http', auth='public', csrf=False)
    def post_call_webhook(self):
        """EL posts conversation metadata after a call ends.

        Creates a connect.call record for calls that arrived via native EL SIP
        attach (where no Twilio webhook fired and Odoo has no call record yet).
        Already-logged calls are deduped by conversation_id so re-delivery is
        safe. Returns an empty 200 on any internal error so EL does not retry.
        """
        logger.info('Incoming request: /connect_elevenlabs/post_call')
        raw_body = http.request.httprequest.get_data(as_text=True) or '{}'
        # EL authenticates post-call webhooks by HMAC signature, not by the tool
        # token header, so verify ElevenLabs-Signature with our stored secret.
        if not self._verify_post_call_signature(raw_body):
            raise Unauthorized()
        try:
            body = json.loads(raw_body)
            # EL wraps the payload under a 'data' key.
            data = body.get('data', body)
        except Exception as e:
            logger.warning('Post call webhook: bad JSON body: %s', e)
            return ''
        try:
            http.request.env['connect.call'].sudo().create_from_elevenlabs_inbound(data)
        except Exception as e:
            logger.exception('Post call webhook: create_from_elevenlabs_inbound failed: %s', e)
        return ''

