# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging
from odoo import api, fields, models, release

logger = logging.getLogger(__name__)


class CallOut(models.Model):
    _inherit = 'connect.callout'

    elevenlabs_enabled = fields.Boolean(compute='_get_elevenlabs_enabled')
    prompt_message_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')
    invalid_input_message_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')
    after_choice_message_file = fields.Many2one('connect.elevenlabs_file', ondelete='set null')

    if release.version_info[0] >= 17.0:
        prompt_message_widget = fields.Html(related='prompt_message_file.preview_audio', string='prompt_message_widget')
        invalid_input_message_widget = fields.Html(
            related='invalid_input_message_file.preview_audio', string='invalid_input_message_widget')
        after_choice_message_widget = fields.Html(related='after_choice_message_file.preview_audio',
                                                  string='after_choice_message_widget')
    else:
        prompt_message_widget = fields.Char(related='prompt_message_file.preview_audio', string='prompt_message_widget')
        invalid_input_message_widget = fields.Char(
            related='invalid_input_message_file.preview_audio', string='invalid_input_message_widget')
        after_choice_message_widget = fields.Char(
            related='after_choice_message_file.preview_audio', string='after_choice_message_widget')

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

    @api.constrains('after_choice_message')
    def _generate_elevenlabs_after_choice_message(self):
        if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
            return
        for rec in self:
            rec._generate_elevenlabs_file('after_choice_message', 'after_choice_message_file')

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

    def get_after_choice_message(self, response):
        try:
            self = self.sudo()
            if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
                return super().get_after_choice_message(response)
            if not self.after_choice_message_file or not self.after_choice_message_file.file:
                self._generate_elevenlabs_after_choice_message()
            response.play(self.after_choice_message_file.get_file_url())
        except Exception as e:
            logger.error('Elevenlabs error: %s', e)
            return super().get_after_choice_message(response)

    def get_invalid_input_message(self, response):
        try:
            self = self.sudo()
            if not self.env['connect.settings'].sudo().get_param('elevenlabs_enabled'):
                return super().get_invalid_input_message(response)
            if not self.invalid_input_message_file or not self.invalid_input_message_file.file:
                self._generate_elevenlabs_invalid_input_message()
            response.play(self.invalid_input_message_file.get_file_url())
        except Exception as e:
            logger.error('Elevenlabs error: %s', e)
            return super().get_invalid_input_message(response)

    def elevenlabs_regenerate_prompts(self):
        callouts = self.env['connect.callout'].sudo().search([])
        for callout in callouts:
            callout._generate_elevenlabs_prompt_message()
            callout._generate_elevenlabs_invalid_input_message()
            callout._generate_elevenlabs_invalid_input_message()
