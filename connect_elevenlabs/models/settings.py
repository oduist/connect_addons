# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.addons.connect.models.settings import PROTECTED_FIELDS

PROTECTED_FIELDS.append('display_elevenlabs_api_key')


class Elevenlabsettings(models.Model):
    _inherit = 'connect.settings'

    elevenlabs_api_key = fields.Char(groups="connect.group_connect_webhook")
    display_elevenlabs_api_key = fields.Char(groups="connect.group_connect_admin")
    elevenlabs_voice = fields.Many2one('connect.elevenlabs_voice', ondelete='set null', string='Selected Voice')
    elevenlabs_enabled = fields.Boolean()

    def elevenlabs_get_voices(self):
        self.env['connect.elevenlabs_voice'].get_voices()

    def open_elevenlabs_form(self):
        rec = self.search([])
        if not rec:
            rec = self.sudo().with_context(no_constrains=True).create({})
        else:
            rec = rec[0]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'connect.settings',
            'res_id': rec.id,
            'name': 'ElevenLabs',
            'view_mode': 'form',
            'view_type': 'form',
            'view_id': self.env.ref('connect_elevenlabs.connect_elevenlabs_settings_form').id,
            'target': 'current',
        }

    def elevenlabs_regenerate_prompts(self):
        self.env['connect.callflow'].elevenlabs_regenerate_prompts()
        self.env['connect.callout'].elevenlabs_regenerate_prompts()

