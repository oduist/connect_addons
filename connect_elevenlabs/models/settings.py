# -*- coding: utf-8 -*-

import logging
import urllib.parse
from urllib.parse import urljoin
import requests
import uuid
from elevenlabs import ElevenLabs

from odoo import fields, models
from odoo.addons.connect.models.settings import PROTECTED_FIELDS
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)

PROTECTED_FIELDS.append('display_elevenlabs_api_key')
PROTECTED_FIELDS.append('display_elevenlabs_post_call_webhook_secret')

class Elevenlabsettings(models.Model):
    _inherit = 'connect.settings'

    elevenlabs_api_key = fields.Char(groups="base.group_erp_manager")
    elevenlabs_agent_token = fields.Char(required=True, groups="base.group_erp_manager",
                                        default=lambda x: str(uuid.uuid4()))
    display_elevenlabs_api_key = fields.Char()
    elevenlabs_voice = fields.Many2one('connect.elevenlabs_voice', ondelete='set null', string='Selected Voice')
    elevenlabs_enabled = fields.Boolean()
    elevenlabs_agent_url = fields.Char(string='Agent URL', required=True, default='https://elevenlabs-agent.ngrok.io')
    elevenlabs_post_call_webhook_url = fields.Char(compute='_get_post_call_webhook_url')
    display_elevenlabs_post_call_webhook_secret = fields.Char()
    elevenlabs_post_call_webhook_secret = fields.Char(groups="base.group_erp_manager")

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


    def _get_post_call_webhook_url(self):
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        self.elevenlabs_post_call_webhook_url = urljoin(api_url, 'connect_elevenlabs/post_call')


    def get_elevenlabs_client(self):
        # Take this using super access because nobody must be able to access it.
        key = self.sudo().get_param('elevenlabs_api_key')
        if not key:
            raise ValidationError('Elevenlabs API key not set!')
        return ElevenLabs(api_key=key)


    def elevenlabs_get_voices(self):
        self.env['connect.elevenlabs_voice'].get_voices()


    def elevenlabs_regenerate_prompts(self):
        self.env['connect.callflow'].elevenlabs_regenerate_prompts()


    def elevenlabs_sync_ai_agents(self):
        self.env['connect.elevenlabs_agent'].sync()


    def elevenlabs_reset_token(self):
        # Generate new token.
        self.set_param('elevenlabs_agent_token', str(uuid.uuid4()))


    def elevenlabs_sync(self):
        self.elevenlabs_get_voices()
        self.elevenlabs_reset_token()
        for agent in self.env['connect.elevenlabs_agent'].search([]):
            agent.update_elevenlabs_agent()
        # self.env['connect.elevenlabs_agent'].sync()
        self.connect_notify('Sync done', title='Elevenlabs Agent', notify_uid=self.env.user.id)

    def ping_agent(self):
        self.ensure_one()
        try:
            response = requests.post(urljoin(self.elevenlabs_agent_url, '/agent/ping'))
            if response.text == 'true':
                self.connect_notify('Pong', title='Elevenlabs Agent', notify_uid=self.env.user.id)
            else:
                response.raise_for_status()
        except Exception as e:
            raise ValidationError(str(e))
