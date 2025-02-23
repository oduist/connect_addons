# -*- coding: utf-8 -*-

import logging
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from elevenlabs import ElevenLabs

logger = logging.getLogger(__name__)

class ElevenlabsVoice(models.Model):
    _name = 'connect.elevenlabs_voice'
    _order = 'id desc'
    _description = 'Elevenlabs Voice'

    voice_id = fields.Char(readonly=True)
    name = fields.Char(readonly=True)
    language = fields.Char(readonly=True)
    accent = fields.Char(readonly=True)
    age = fields.Char(readonly=True)
    gender = fields.Char(readonly=True)
    preview_url = fields.Char(readonly=True)
    if release.version_info[0] >= 17.0:
        preview_audio = fields.Html(compute='_compute_preview_audio', string='Preview Audio', sanitize=False)
    else:
        preview_audio = fields.Char(compute='_compute_preview_audio', string='Preview Audio')
    description = fields.Char()

    _sql_constraints = [('voice_id_unique', 'UNIQUE(voice_id)', 'This Voice is already added!')]

    @api.depends('preview_url')
    def _compute_preview_audio(self):
        for record in self:
            if record.preview_url:
                record.preview_audio = f"""
                    <audio controls>
                        <source src="{record.preview_url}" type="audio/mpeg">
                        Your browser does not support the audio element.
                    </audio>
                """
            else:
                record.preview_audio = "No audio preview available."

    @api.model
    def get_voices(self):
        key = self.env['connect.settings'].sudo().get_param('elevenlabs_api_key')
        if not key:
            raise ValidationError('Elevenlabs API key not set!')
        client = ElevenLabs(api_key=key)
        response = client.voices.get_all()
        elevenlabs_voice_ids = set([k.voice_id for k in response.voices])
        odoo_voice_ids = set(self.search([]).mapped('voice_id'))
        for v in response.voices:
            if v.voice_id not in odoo_voice_ids:
                # New voice added
                self.create({
                    'voice_id': v.voice_id,
                    'name': v.name,
                    'language': v.fine_tuning.language,
                    'accent': v.labels.get('accent'),
                    'age': v.labels.get('age'),
                    'gender': v.labels.get('gender'),
                    'preview_url': v.preview_url,
                    'description': v.labels.get('description'),
                })
                logger.info('Added new voice: %s ID: %s', v.name, v.voice_id)
        # Remove in Odoo absent voices.
        voices_to_remove = odoo_voice_ids - elevenlabs_voice_ids
        self.search([('voice_id', 'in', list(voices_to_remove))]).unlink()
        # Check if current voice was removed and set to another voice.
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_voice'):
            last = self.search([], order='id desc')[0]
            self.env['connect.settings'].sudo().set_param(
                'elevenlabs_voice', last)
            logger.warning('Current elevellabs voice not set, setting to %s ID: %s',
                           last.name, last.voice_id)

