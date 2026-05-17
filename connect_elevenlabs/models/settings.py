# -*- coding: utf-8 -*-

import logging
from urllib.parse import urljoin
import uuid
from elevenlabs import ElevenLabs

from odoo import fields, models
from odoo.addons.connect.models.license import ODUIST_MODULES
from odoo.addons.connect.models.settings import PROTECTED_FIELDS
from odoo.exceptions import ValidationError

ODUIST_MODULES.append('connect_elevenlabs')

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
    elevenlabs_post_call_webhook_url = fields.Char(compute='_get_post_call_webhook_url')
    elevenlabs_conversation_initiation_webhook_url = fields.Char(
        compute='_get_conversation_initiation_webhook_url')
    display_elevenlabs_post_call_webhook_secret = fields.Char()
    elevenlabs_post_call_webhook_secret = fields.Char(groups="base.group_erp_manager")
    # Transcript elevenlabs webhook
    transcript_provider = fields.Selection(
        selection_add=[('elevenlabs', 'Elevenlabs')], ondelete={'elevenlabs': 'set default'})

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

    def _get_conversation_initiation_webhook_url(self):
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        self.elevenlabs_conversation_initiation_webhook_url = urljoin(
            api_url, 'connect_elevenlabs/conversation_initiation')

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


    def elevenlabs_sync_tools(self):
        """Sync all tools to ElevenLabs (create or update).
        System tools are excluded — they are managed via agent config (PATCH agent)."""
        tools = self.env['connect.elevenlabs_agent_tool'].search([('tool_type', '!=', 'system')])
        for tool in tools:
            if tool.tool_id:
                tool.update_elevenlabs_tool()
            else:
                tool._sync_to_elevenlabs()
        self.connect_notify('Tools sync done!', title='Elevenlabs Agent', notify_uid=self.env.user.id)

    def elevenlabs_sync(self):
        if not self.env['oduist.license'].check_license('connect_elevenlabs', silent=True):
            return False
        self.elevenlabs_get_voices()
        self.connect_notify('Voices sync done!', title='Elevenlabs Agent', notify_uid=self.env.user.id)
        self.elevenlabs_reset_token()
        # Sync tools (create new + update existing with new token)
        self.elevenlabs_sync_tools()

        for agent in self.env['connect.elevenlabs_agent'].search([]):
            agent.update_elevenlabs_agent()
        self.connect_notify('Sync done', title='Elevenlabs Agent', notify_uid=self.env.user.id)

    def elevenlabs_unbind_account(self):
        """Sync with new ElevenLabs account: clear agent and tool IDs"""
        # Clear all agent UIDs
        self.env['connect.elevenlabs_agent'].with_context(skip_elevenlabs=True).search([]).write({'agent_uid': None})
        # Clear all tool IDs
        self.env['connect.elevenlabs_agent_tool'].with_context(skip_elevenlabs=True).search([]).write(
            {'tool_id': None, 'synced': False})

        self.connect_notify('Unbind done!', title='Elevenlabs Agent', notify_uid=self.env.user.id)
