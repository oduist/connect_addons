# -*- coding: utf-8 -*

import json
import logging
import requests
from odoo import http, SUPERUSER_ID, registry, release
from werkzeug.exceptions import BadRequest, NotFound

from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class ConnectPlusController(http.Controller):

    @http.route('/connect/transcript/<int:rec_id>', methods=['POST'], type='json',
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

    @http.route('/connect/query_result/', methods=['POST'], type='json', auth='public', csrf=False)
    def query_result(self, **kw):
        rec = http.request.env['connect.query'].sudo().search([
            ('id', '=', kw.get('rec_id')),
            ('token', '=', kw.get('token'))
        ])
        if not rec:
            raise NotFound()
        rec.update({
            'result': kw.get('result'),
            'error': kw.get('error'),
            'price': kw.get('price'),
            'token': ''
        })
