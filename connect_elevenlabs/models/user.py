# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging
from odoo import models, fields, release, api

logger = logging.getLogger(__name__)


class ElevenLabsUser(models.Model):
    _inherit = 'connect.user'

    elevenlabs_enabled = fields.Boolean(compute='_get_elevenlabs_enabled')
    voicemail_prompt_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')
    if release.version_info[0] >= 17.0:
        voicemail_prompt_widget = fields.Html(related='voicemail_prompt_file.preview_audio')
    else:
        voicemail_prompt_widget = fields.Char(related='voicemail_prompt_file.preview_audio')

    def _get_elevenlabs_enabled(self):
        elevenlabs_enabled = self.env['connect.settings'].sudo().get_param('elevenlabs_enabled')
        for rec in self:
            rec.elevenlabs_enabled = elevenlabs_enabled

    @api.constrains('voicemail_prompt', 'voicemail_enabled')
    def _generate_elevenlabs_voicemail_prompt(self):
        elevenlabs_enabled = self.env['connect.settings'].sudo().get_param('elevenlabs_enabled')
        for rec in self:
            if elevenlabs_enabled and rec.voicemail_enabled:
                voicemail_prompt = rec.render_voicemail_prompt()
                if rec.voicemail_prompt_file:
                    rec.voicemail_prompt_file.text = voicemail_prompt
                else:
                    rec.voicemail_prompt_file = self.env['connect.elevenlabs_file'].create({'text': voicemail_prompt})

    def get_voicemail_prompt(self, response):
        try:
            self = self.sudo()
            if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
                return super().get_voicemail_prompt(response)
            if not self.voicemail_prompt_file or self.voicemail_prompt_file.file:
                self._generate_elevenlabs_voicemail_prompt()
            response.play(self.voicemail_prompt_file.get_file_url())
        except Exception as e:
            logger.error('Elevenlabs error: %s', e)
            return super().get_voicemail_prompt(response)
