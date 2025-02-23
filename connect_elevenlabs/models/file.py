# -*- coding: utf-8 -*-

import base64
import logging
from urllib.parse import urljoin
import uuid
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from elevenlabs import ElevenLabs

logger = logging.getLogger(__name__)


class ElevenlabsFile(models.Model):
    _name = 'connect.elevenlabs_file'
    _description = 'Elevenlabs file'

    text = fields.Char(required=True)
    file = fields.Binary(attachment=True)
    filename = fields.Char()
    if release.version_info[0] >= 17.0:
        preview_audio = fields.Html(compute='_compute_preview_audio', string='Preview Audio', sanitize=False)
    else:
        preview_audio = fields.Char(compute='_compute_preview_audio', string='Preview Audio')

    @api.constrains('text')
    def _regenerate_file(self):
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
            return
        for rec in self:
            rec.write({
                'file': rec.generate_elevenlabs_voice(rec.text),
                'filename': '{}.mp3'.format(uuid.uuid4().hex),
            })

    def get_file_path(self):
        return '/web/content/connect.elevenlabs_file/{}/file/{}'.format(self.id, self.filename)

    def get_file_url(self):
        instance_uid = self.env['connect.settings'].sudo().get_param('instance_uid')
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        if 'api-' in api_url:
            api_url = api_url.replace('api-', 'media-')
        media_url = self.env['connect.settings'].sudo().get_param('media_url')
        if media_url:
            api_url = media_url
        url = urljoin(api_url, 'proxy/{}/content/connect.elevenlabs_file/{}/file/{}'.format(
            instance_uid, self.id, self.filename)
        )
        return url

    def _compute_preview_audio(self):
        for rec in self:
            rec.preview_audio = '<audio id="sound_file" preload="auto" ' \
                'controls="controls"><source src="{}"/></audio>'.format(rec.get_file_path())

    def generate_elevenlabs_voice(self, text):
        try:
            client = ElevenLabs(api_key=self.env['connect.settings'].sudo().get_param('elevenlabs_api_key'))
            audio = client.generate(text=text,
                voice=self.env['connect.settings'].sudo().get_param('elevenlabs_voice').voice_id,
                model="eleven_multilingual_v2"
            )
            data = b''.join(audio)
            return base64.b64encode(data).decode('utf-8')
        except Exception as e:
            logger.exception('Elevenlabs error:')
            raise ValidationError('Elevenlabs error: {}'.format(e))

