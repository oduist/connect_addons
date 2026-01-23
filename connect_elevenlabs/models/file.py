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

    @api.model_create_multi
    def create(self, vals_list):
        res = super(ElevenlabsFile, self).create(vals_list)
        for rec in res:
            # Force the mime type.
            attachment = self.env["ir.attachment"].search([
                ("res_model", "=", "connect.elevenlabs_file"),
                ("res_field", "=", "file"),
                ("res_id", "=", rec.id),
            ], limit=1)
            attachment.mimetype = "audio/mpeg"
        return res

    @api.constrains('text')
    def _regenerate_file(self):
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
            return
        for rec in self:
            rec.write({
                'file': rec.generate_elevenlabs_voice(rec.text),
                'filename': '{}.mp3'.format(uuid.uuid4().hex),
            })
            # Fix for users of version 1.0.1 with "application/octet-stream" issue.
            # TODO: Remove this code in future.
            attachment = self.env["ir.attachment"].search([
                ("res_model", "=", "connect.elevenlabs_file"),
                ("res_field", "=", "file"),
                ("res_id", "=", rec.id),
            ], limit=1)
            if attachment and attachment.mimetype != 'audio/mpeg':
                attachment.mimetype = "audio/mpeg"


    def get_file_path(self):
        return '/web/content/connect.elevenlabs_file/{}/file/{}'.format(self.id, self.filename)

    def get_file_url(self):
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        url = urljoin(api_url, '/web/content/connect.elevenlabs_file/{}/file/{}'.format(
            self.id, self.filename)
        )
        return url

    def _compute_preview_audio(self):
        for rec in self:
            rec.preview_audio = '<audio id="sound_file" preload="auto" ' \
                'controls="controls"><source src="{}"/></audio>'.format(rec.get_file_path())

    def generate_elevenlabs_voice(self, text):
        try:
            client = self.env['connect.settings'].get_elevenlabs_client()
            audio = client.generate(text=text,
                voice=self.env['connect.settings'].sudo().get_param('elevenlabs_voice').voice_id,
                model="eleven_multilingual_v2"
            )
            data = b''.join(audio)
            return base64.b64encode(data).decode('utf-8')
        except Exception as e:
            logger.exception('Elevenlabs error:')
            raise ValidationError('Elevenlabs error: {}'.format(e))
