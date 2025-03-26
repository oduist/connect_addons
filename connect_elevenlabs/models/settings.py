# -*- coding: utf-8 -*-

import logging
from urllib.parse import urljoin

import requests
from odoo.addons.connect.models.settings import PROTECTED_FIELDS

from odoo import fields, models
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)

PROTECTED_FIELDS.append('display_elevenlabs_api_key')


class Elevenlabsettings(models.Model):
    _inherit = 'connect.settings'

    elevenlabs_api_key = fields.Char(groups="connect.group_connect_webhook")
    display_elevenlabs_api_key = fields.Char(groups="connect.group_connect_admin")
    elevenlabs_voice = fields.Many2one('connect.elevenlabs_voice', ondelete='set null', string='Selected Voice')
    elevenlabs_enabled = fields.Boolean()
    agent_url = fields.Char(string='Agent URL', required=True, default='https://localhost:48000')

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
            'view_id': self.env.ref('connect_elevenlabs.connect_elevenlabs_settings_form').id,
            'target': 'current',
        }

    def elevenlabs_regenerate_prompts(self):
        self.env['connect.callflow'].elevenlabs_regenerate_prompts()

    def ping_agent(self):
        self.ensure_one()
        try:
            response = requests.post(urljoin(self.agent_url, '/agent/ping'))
            if response.text == 'true':
                self.connect_notify('Pong', title='Elevenlabs Agent', notify_uid=self.env.user.id)
            else:
                response.raise_for_status()
        except Exception as e:
            raise ValidationError(str(e))

