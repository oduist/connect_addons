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
        media_name = '{}.wav'.format(media_url.split('/')[-1])
        account_sid = http.request.env['connect.settings'].sudo().get_param('account_sid')
        auth_token = http.request.env['connect.settings'].sudo().get_param('auth_token')
        response = requests.get(media_url, auth=(account_sid, auth_token))
        if response.status_code == 200:
            # Create the response
            res = http.Response(response.content, content_type='audio/wav')
            res.headers['Content-Disposition'] = http.content_disposition(media_name)
            return res
        else:
            raise UserError("Failed to download the media. Status code: %s" % response.status_code)

    @http.route("/connect/ai_completion", type=route_type, auth="user")
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
