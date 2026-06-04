# -*- coding: utf-8 -*

import json
import logging
import os
from datetime import timedelta

import openai
import requests
from werkzeug.exceptions import NotFound

from odoo import fields, http, release, tools
from odoo.api import SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.addons.connect.models import s3_utils

logger = logging.getLogger(__name__)

route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'

class ConnectController(http.Controller):

    @http.route('/connect/transcript/<int:rec_id>', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def upload_transcript(self, rec_id):
        # Public method protected by the one-time transcription token.
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        rec = http.request.env['connect.recording'].sudo().search([
            ('id', '=', rec_id), ('transcription_token', '!=', False),
            ('transcription_token', '=', data['transcription_token'])
        ])
        if not rec:
            logger.warning('Transcription token %s not found for recording %s',
                data['transcription_token'], rec_id)
            raise NotFound()
        rec.with_user(SUPERUSER_ID).update_transcript(data)
        logger.info('Transcript for recording %s saved.', rec_id)
        return True

    @http.route('/connect/recording/<int:record_id>', type='http', auth='user')
    def serve_recording(self, record_id):
        # Access the recording as logged in user.
        recording = http.request.env['connect.recording'].browse(record_id)
        if not recording.exists() or not recording.media_url:
            return http.Response(status=404)
        return self._serve_media(recording.media_url)

    @http.route('/connect/voicemail/<int:record_id>', type='http', auth='user')
    def serve_voicemail(self, record_id):
        # Access the recording as logged in user.
        call = http.request.env['connect.call'].browse(record_id)
        if not call.exists() or not call.voicemail_url:
            return http.Response(status=404)
        return self._serve_media(call.voicemail_url)

    def _serve_media(self, media_url):
        settings = http.request.env['connect.settings'].sudo()
        bucket = settings.get_param('aws_s3_bucket')
        if settings.get_param('s3_recordings_enabled') and s3_utils.is_s3_media_url(media_url, bucket):
            key = s3_utils.parse_s3_key(media_url, bucket)
            s3 = settings._get_s3_client()
            try:
                obj = s3.get_object(Bucket=bucket, Key=key)
            except s3.exceptions.NoSuchKey:
                return http.Response(status=410)  # gone (lifecycle-expired)
            data = obj['Body'].read()
            res = http.Response(data, content_type=obj.get('ContentType') or 'audio/mpeg')
            res.headers['Content-Disposition'] = http.content_disposition(key.split('/')[-1])
            return res
        media_name = '{}.wav'.format(media_url.split('/')[-1])
        account_sid = settings.get_param('account_sid')
        auth_token = settings.get_param('auth_token')
        response = requests.get(media_url, auth=(account_sid, auth_token))
        if response.status_code == 200:
            # Create the response
            res = http.Response(response.content, content_type='audio/wav')
            res.headers['Content-Disposition'] = http.content_disposition(media_name)
            return res
        else:
            raise UserError("Failed to download the media. Status code: %s" % response.status_code)

    @http.route('/connect/<string:extension_number>', methods=['GET', 'POST'], type='http', auth='public', csrf=False)
    def extension_handler(self, extension_number, **kw):
        """Handle extension calls via direct URL"""
        exten = http.request.env['connect.exten'].sudo().search([('number', '=', extension_number)])
        if not exten:
            return '<Response><Say>Extension not found. Goodbye!</Say></Response>'
        return exten.render(request=kw, params=kw)

    @http.route('/connect/dial_complete', methods=['GET', 'POST'], type='http', auth='public', csrf=False)
    def dial_complete_handler(self, **kw):
        """Handle Dial action completion for transfer redirects and update call completion fields"""
        from twilio.twiml.voice_response import VoiceResponse

        dial_status = kw.get('DialCallStatus')
        dial_call_sid = kw.get('DialCallSid')
        original_call_sid = kw.get('CallSid')

        try:
            self._process_extension_redirect_completion(kw)
        except Exception as e:
            logger.error(f'Failed to process transfer completion: {e}', exc_info=True)

        response = VoiceResponse()

        if dial_status == 'completed':
            response.hangup()
        else:
            try:
                original_call = self._find_original_call_for_redirect_completion(original_call_sid, dial_call_sid)
                if original_call:
                    transfer_recipient = None

                    if original_call_sid:
                        transfer_recipient = original_call.get_transfer_target(original_call_sid)

                    if not transfer_recipient and dial_call_sid:
                        transfer_recipient = original_call.get_transfer_target(dial_call_sid)

                    if not transfer_recipient:
                        parent_call_sid = kw.get('ParentCallSid')
                        if parent_call_sid:
                            transfer_recipient = original_call.get_transfer_target(parent_call_sid)

                    if not transfer_recipient and original_call.transferred_users:
                        transfer_recipient = original_call.transferred_users[-1]

                    if transfer_recipient:
                        pbx_user = http.request.env['connect.user'].sudo().search([
                            ('user', '=', transfer_recipient.id)
                        ], limit=1)

                        if pbx_user and pbx_user.voicemail_enabled and pbx_user.voicemail_prompt:
                            personalized_prompt = pbx_user.render_voicemail_prompt()
                            system_voice = http.request.env['connect.settings'].get_system_voice()
                            processed_text = http.request.env['connect.settings'].process_pronunciation(personalized_prompt)
                            response.say(processed_text, voice=system_voice)
                        else:
                            system_voice = http.request.env['connect.settings'].get_system_voice()
                            processed_text = http.request.env['connect.settings'].process_pronunciation('Please leave a message after the tone.')
                            response.say(processed_text, voice=system_voice)
                    else:
                        logger.warning(f'Could not find transfer recipient for personalized voicemail')
                        system_voice = http.request.env['connect.settings'].get_system_voice()
                        processed_text = http.request.env['connect.settings'].process_pronunciation('Please leave a message after the tone.')
                        response.say(processed_text, voice=system_voice)
                else:
                    logger.warning(f'Could not find original call for personalized voicemail')
                    system_voice = http.request.env['connect.settings'].get_system_voice()
                    processed_text = http.request.env['connect.settings'].process_pronunciation('Please leave a message after the tone.')
                    response.say(processed_text, voice=system_voice)
            except Exception as e:
                logger.error(f'Error setting up personalized voicemail: {e}')
                system_voice = http.request.env['connect.settings'].get_system_voice()
                processed_text = http.request.env['connect.settings'].process_pronunciation('Please leave a message after the tone.')
                response.say(processed_text, voice=system_voice)

            response.record(maxLength=120, finishOnKey='#', playBeep=True)

        return response.to_xml()

    def _process_extension_redirect_completion(self, webhook_params):
        """
        Process completion of extension redirect transfers.
        Updates the original call's completion fields based on transfer outcome.
        """
        dial_call_status = webhook_params.get('DialCallStatus')
        dial_call_sid = webhook_params.get('DialCallSid')
        original_call_sid = webhook_params.get('CallSid')

        original_call = self._find_original_call_for_redirect_completion(original_call_sid, dial_call_sid)
        if not original_call:
            logger.warning(f'Could not find original call for redirect completion')
            return

        transfer_recipient = None

        if original_call_sid:
            transfer_recipient = original_call.get_transfer_target(original_call_sid)

        if not transfer_recipient and dial_call_sid:
            transfer_recipient = original_call.get_transfer_target(dial_call_sid)

        if not transfer_recipient:
            parent_call_sid = webhook_params.get('ParentCallSid')
            if parent_call_sid:
                transfer_recipient = original_call.get_transfer_target(parent_call_sid)

        if not transfer_recipient and original_call.transferred_users:
            transfer_recipient = original_call.transferred_users[-1]

        if not transfer_recipient:
            logger.warning(f'Could not find transfer recipient for completion processing - no transferred_users found')
            return

        if dial_call_status == 'completed':
            original_call.completed_by_user = transfer_recipient
            self._create_or_update_transfer_channel(original_call, dial_call_sid, transfer_recipient, 'completed', webhook_params)
            self._terminate_external_call_after_transfer_completion(original_call, dial_call_sid, transfer_recipient)
        else:
            self._create_or_update_transfer_channel(original_call, dial_call_sid, transfer_recipient, dial_call_status, webhook_params)

    def _find_original_call_for_redirect_completion(self, original_call_sid, dial_call_sid):
        """Find the original call that initiated this transfer redirect"""
        Call = http.request.env['connect.call'].sudo()
        cutoff = fields.Datetime.now() - timedelta(minutes=5)

        recent_calls = Call.search([
            ('transfer_context', '!=', False),
            ('create_date', '>=', cutoff),
        ])

        for call in recent_calls:
            if call.transfer_context:
                context_str = str(call.transfer_context)
                if ((original_call_sid and original_call_sid in context_str) or
                    (dial_call_sid and dial_call_sid in context_str)):
                    return call

        # Fallback: find recent calls with transfers still in progress
        recent_transfers = Call.search([
            ('transferred_users', '!=', False),
            ('create_date', '>=', cutoff),
            ('status', 'not in', ['completed', 'failed', 'busy', 'no-answer']),
        ], limit=5)

        if recent_transfers:
            return recent_transfers[0]

        return None

    def _create_or_update_transfer_channel(self, call, dial_call_sid, transfer_recipient, status, webhook_params):
        """Create or update a channel record for the transfer recipient to ensure proper field population"""
        try:
            existing_channel = http.request.env['connect.channel'].sudo().search([
                ('sid', '=', dial_call_sid),
                ('call', '=', call.id)
            ], limit=1)

            if existing_channel:
                logger.info(f'Updating existing transfer channel {existing_channel.id}')
                existing_channel.write({
                    'status': status,
                    'duration': int(webhook_params.get('DialCallDuration', 0))
                })
                return existing_channel
            else:
                logger.info(f'Creating new transfer channel for {transfer_recipient.login}')

                parent_channel = call.channels.filtered(lambda c: not c.parent_channel)
                if not parent_channel:
                    logger.warning(f'No parent channel found for call {call.id}')
                    return None
                parent_channel = parent_channel[0]

                pbx_user = http.request.env['connect.user'].sudo().search([
                    ('user', '=', transfer_recipient.id)
                ], limit=1)

                if not pbx_user:
                    logger.warning(f'No PBX user found for {transfer_recipient.login}')
                    return None

                channel_data = {
                    'sid': dial_call_sid,
                    'call': call.id,
                    'parent_channel': parent_channel.id,
                    'technical_direction': 'outbound-dial',
                    'status': status,
                    'duration': int(webhook_params.get('DialCallDuration', 0)),
                    'called_pbx_user': pbx_user.id,
                    'called_user': transfer_recipient.id,
                    'call_source': 'transfer',
                    'caller': parent_channel.caller,
                    'called': pbx_user.uri
                }

                new_channel = http.request.env['connect.channel'].sudo().create(channel_data)
                logger.info(f'Created transfer channel {new_channel.id} for {transfer_recipient.login}')
                return new_channel

        except Exception as e:
            logger.error(f'Failed to create/update transfer channel: {e}', exc_info=True)
            return None

    def _terminate_external_call_after_transfer_completion(self, call, transfer_recipient_sid, transfer_recipient):
        """
        Terminate external call legs after successful transfer completion to prevent voicemail fall-through.
        This addresses the issue where external callers go to voicemail when internal users hang up completed calls.
        """
        try:
            if call.direction == 'outgoing':
                external_call_sid = call.get_external_call_leg()
                if external_call_sid:
                    client = http.request.env['connect.settings'].sudo().get_client()
                    try:
                        external_call = client.calls(external_call_sid).fetch()
                        if external_call.status in ['in-progress', 'ringing']:
                            self._store_external_call_termination_context(call, external_call_sid, transfer_recipient_sid)
                        else:
                            logger.info(f'External call {external_call_sid} already ended ({external_call.status})')
                    except Exception as e:
                        logger.warning(f'Could not check external call status: {e}')
                else:
                    logger.warning(f'No external call leg found for outgoing call {call.id}')
            else:
                external_channels = call.channels.filtered(lambda c: not c.parent_channel and not c.caller_pbx_user)
                if external_channels:
                    external_channel = external_channels[0]
                    self._store_external_call_termination_context(call, external_channel.sid, transfer_recipient_sid)
                else:
                    logger.info(f'No external caller channel found for incoming call {call.id}')

        except Exception as e:
            logger.error(f'Failed to set up external call termination: {e}', exc_info=True)

    def _store_external_call_termination_context(self, call, external_call_sid, transfer_recipient_sid):
        """Store context for terminating external calls when transfer recipients hang up"""
        try:
            current_context = call.transfer_context or {}
            current_context['_external_termination'] = {
                'external_call_sid': external_call_sid,
                'transfer_recipient_sid': transfer_recipient_sid,
                'setup_time': http.request.env.cr.now()
            }
            call.transfer_context = current_context
        except Exception as e:
            logger.error(f'Failed to store external termination context: {e}')

    @http.route("/connect/ai_completion", type="json", auth="user")
    def ai_completion(self, model, res_id):
        openai_api_key = http.request.env["connect.settings"].sudo().get_param("openai_api_key")
        if not openai_api_key:
            return {"status": "fail", "error_message": "Missing OpenAI API key!"}
        records = (
            http.request.env["mail.message"]
            .sudo()
            .search([("res_id", "=", res_id), ("model", "=", model)], order="id desc")
        )
        data = []
        for rec in records:
            if rec.message_type == "notification":
                continue
            data.append(f"{rec.author_id.name or 'Anonymous'}: {tools.html2plaintext(rec.body)}")
        segments = "\n".join(data)

        client = openai.OpenAI(api_key=openai_api_key)

        default_prompt = "Continue the conversation naturally!"
        prompt = http.request.env["connect.settings"].sudo().get_param("chatter_message_generate_prompt")

        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_COMPLETION_MODEL", "gpt-4o"),
            messages=[
                {"role": "user", "content": f"{prompt or default_prompt} \nOmit dialog name from final message!"},
                {
                    "role": "user",
                    "content": segments,
                },
            ],
            temperature=float(os.environ.get("OPENAI_COMPLETION_TEMPERATURE", 0.5)),
            max_tokens=int(os.environ.get("OPENAI_COMPLETION_MAX_TOKENS", 4096)),
            top_p=float(os.environ.get("OPENAI_COMPLETION_TOP_P", 1.0)),
            frequency_penalty=float(os.environ.get("OPENAI_COMPLETION_FREQUENCY_PENALTY", 0.0)),
            presence_penalty=float(os.environ.get("OPENAI_COMPLETION_PRESENSE_PENALTY", 0.0)),
        )
        logger.info("%s", response.usage)
        message = response.choices[0].message.content.strip("\n\n")
        return {"status": "ok", "message": message}

    @http.route('/connect/health/<string:uid>/', methods=['GET', 'POST'], type='http', auth='public', csrf=False)
    def health_check(self, uid):
        instance_uid = http.request.env['oduist.license'].sudo().get_param('instance_uid')
        if uid == instance_uid:
            return "True"
        else:
            return "False"
