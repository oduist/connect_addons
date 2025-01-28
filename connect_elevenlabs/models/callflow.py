# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging

from odoo import models, fields, release, api

logger = logging.getLogger(__name__)


class ElevenLabsCallflow(models.Model):
    _inherit = 'connect.callflow'

    elevenlabs_enabled = fields.Boolean(compute='_get_elevenlabs_enabled')
    prompt_message_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')
    invalid_input_message_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')
    voicemail_prompt_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')
    if release.version_info[0] >= 17.0:
        prompt_message_widget = fields.Html(related='prompt_message_file.preview_audio', string='prompt_message_widget')
        invalid_input_message_widget = fields.Html(
            related='invalid_input_message_file.preview_audio', string='invalid_input_message_widget')
        voicemail_prompt_widget = fields.Html(
            related='voicemail_prompt_file.preview_audio', string='voicemail_prompt_widget')
    else:
        prompt_message_widget = fields.Char(related='prompt_message_file.preview_audio', string='prompt_message_widget')
        invalid_input_message_widget = fields.Char(
            related='invalid_input_message_file.preview_audio', string='invalid_input_message_widget')
        voicemail_prompt_widget = fields.Char(
            related='voicemail_prompt_file.preview_audio', string='voicemail_prompt_widget')

    def _get_elevenlabs_enabled(self):
        elevenlabs_enabled = self.env['connect.settings'].sudo().get_param('elevenlabs_enabled')
        for rec in self:
            rec.elevenlabs_enabled = elevenlabs_enabled

    @api.constrains('prompt_message')
    def _generate_elevenlabs_prompt_message(self):
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
            return
        for rec in self:
            rec._generate_elevenlabs_file('prompt_message', 'prompt_message_file')

    @api.constrains('invalid_input_message')
    def _generate_elevenlabs_invalid_input_message(self):
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
            return
        for rec in self:
            rec._generate_elevenlabs_file('invalid_input_message', 'invalid_input_message_file')

    @api.constrains('voicemail_prompt')
    def _generate_elevenlabs_voicemail_prompt(self):
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
            return
        for rec in self:
            rec._generate_elevenlabs_file('voicemail_prompt', 'voicemail_prompt_file')

    def _generate_elevenlabs_file(self, prompt_field, file_field):
        self = self.sudo()
        self.ensure_one()
        if getattr(self, prompt_field):
            if getattr(self, file_field):
                # Update
                getattr(self, file_field).text = getattr(self, prompt_field)
            else:
                setattr(self, file_field, self.env['connect.elevenlabs_file'].create({
                    'text': getattr(self, prompt_field),
                }))
        else:
            if getattr(self, file_field):
                getattr(self, file_field).unlink()

    def get_prompt_message(self, gather):
        try:
            self = self.sudo()
            if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
                return super().get_prompt_message(gather)
            if not self.prompt_message_file or not self.prompt_message_file.file:
                self._generate_elevenlabs_prompt_message()
            gather.play(self.prompt_message_file.get_file_url())
        except Exception as e:
            logger.error('Elevenlabs error: %s', e)
            return super().get_prompt_message(gather)

    def get_gather_invalid_input_message(self, response):
        try:
            self = self.sudo()
            if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
                return super().get_gather_invalid_input_message(response)
            if not self.invalid_input_message_file or not self.invalid_input_message_file.file:
                self._generate_elevenlabs_invalid_input_message()
            response.play(self.invalid_input_message_file.get_file_url())
        except Exception as e:
            logger.error('Elevenlabs error: %s', e)
            return super().get_gather_invalid_input_message(response)

    def get_voicemail_prompt_message(self, response):
        try:
            self = self.sudo()
            if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
                return super().get_voicemail_prompt_message(response)
            if not self.voicemail_prompt_file or self.voicemail_prompt_file.file:
                self._generate_elevenlabs_voicemail_prompt()
            response.play(self.voicemail_prompt_file.get_file_url())
        except Exception as e:
            logger.error('Elevenlabs error: %s', e)
            return super().get_voicemail_prompt_message(response)

    def elevenlabs_regenerate_prompts(self):
        callflows = self.env['connect.callflow'].sudo().search([])
        for callflow in callflows:
            callflow._generate_elevenlabs_prompt_message()
            callflow._generate_elevenlabs_invalid_input_message()
            callflow._generate_elevenlabs_voicemail_prompt()