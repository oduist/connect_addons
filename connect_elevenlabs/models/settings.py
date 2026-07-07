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

class Elevenlabsettings(models.Model):
    _inherit = 'connect.settings'

    elevenlabs_api_key = fields.Char(groups="base.group_erp_manager")
    elevenlabs_agent_token = fields.Char(required=True, groups="base.group_erp_manager",
                                        default=lambda x: str(uuid.uuid4()))
    display_elevenlabs_api_key = fields.Char()
    elevenlabs_voice = fields.Many2one('connect.elevenlabs_voice', ondelete='set null', string='Selected Voice')
    elevenlabs_enabled = fields.Boolean()
    elevenlabs_conversation_initiation_webhook_url = fields.Char(
        compute='_get_conversation_initiation_webhook_url')
    # Post-call webhook the module owns (HMAC): EL only authenticates post-call
    # webhooks by HMAC signature, so we create the webhook entity ourselves and
    # keep its secret to verify inbound deliveries.
    elevenlabs_post_call_webhook_id = fields.Char(
        groups="base.group_erp_manager", readonly=True)
    elevenlabs_post_call_webhook_secret = fields.Char(
        groups="base.group_erp_manager", readonly=True)
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

    def _get_conversation_initiation_webhook_url(self):
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        self.elevenlabs_conversation_initiation_webhook_url = urljoin(
            api_url, 'connect_elevenlabs/conversation_initiation')

    def get_elevenlabs_client(self):
        # Take this using super access because nobody must be able to access it.
        # Strip stray whitespace: a leading/trailing space in the pasted key
        # makes httpx reject the xi-api-key header (LocalProtocolError:
        # "Illegal header value").
        key = (self.sudo().get_param('elevenlabs_api_key') or '').strip()
        if not key:
            raise ValidationError('Elevenlabs API key not set!')
        return ElevenLabs(api_key=key)

    def _push_elevenlabs_initiation_webhook(self):
        """Push the Conversation Initiation Client Data Webhook to EL workspace settings.

        This is the workspace-level webhook (PATCH /v1/convai/settings) — one
        config for all agents in the account. URL and token come from this
        record; agent-level overrides are intentionally not used.
        """
        rec = self.sudo()
        if not rec.elevenlabs_enabled:
            return
        url = rec.elevenlabs_conversation_initiation_webhook_url
        token = rec.elevenlabs_agent_token
        if not url or not token:
            return
        try:
            client = rec.get_elevenlabs_client()
        except ValidationError:
            return
        try:
            client.conversational_ai.settings.update(
                conversation_initiation_client_data_webhook={
                    "url": url,
                    "request_headers": {
                        "x-elevenlabs-agent-token": token,
                    },
                },
            )
            logger.info("EL initiation webhook pushed: %s", url)
        except Exception as e:
            logger.exception("EL initiation webhook push failed: %s", e)

    def _push_elevenlabs_post_call_webhook(self):
        """Own the workspace post-call webhook so we can verify its HMAC.

        EL authenticates post-call webhooks only by HMAC signature (no custom
        header like the initiation webhook), so the module creates the webhook
        entity itself, stores the returned secret, and selects it for post-call
        delivery. Re-creates it when the api_url drifts (the secret is rotated
        and re-stored). The controller verifies ElevenLabs-Signature with the
        stored secret.
        """
        import httpx
        rec = self.sudo()
        if not rec.elevenlabs_enabled:
            return
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        if not api_url:
            return
        url = urljoin(api_url, 'connect_elevenlabs/post_call')
        key = rec.get_param('elevenlabs_api_key')
        if not key:
            return
        base = "https://api.elevenlabs.io/v1/workspace/webhooks"
        headers = {"xi-api-key": key}
        webhook_id = rec.get_param('elevenlabs_post_call_webhook_id')
        secret = rec.get_param('elevenlabs_post_call_webhook_secret')
        # Reuse the existing webhook if it still points at the current url and
        # we already hold its secret; otherwise (re)create it.
        reuse = False
        if webhook_id and secret:
            try:
                resp = httpx.get(base, headers=headers, timeout=20)
                for w in (resp.json().get('webhooks') or []):
                    if (w.get('webhook_id') == webhook_id
                            and w.get('webhook_url') == url
                            and not w.get('is_disabled')):
                        reuse = True
                        break
            except Exception as e:
                logger.warning("EL post-call webhook lookup failed: %s", e)
        if not reuse:
            try:
                resp = httpx.post(base, headers=headers, timeout=20, json={
                    "settings": {
                        "auth_type": "hmac",
                        "name": "connect post_call ({})".format(
                            rec.get_param('db_name') or self.env.cr.dbname),
                        "webhook_url": url,
                    }
                })
                resp.raise_for_status()
                data = resp.json()
                webhook_id = data.get('webhook_id')
                secret = data.get('webhook_secret') or secret
                self.set_param('elevenlabs_post_call_webhook_id', webhook_id)
                if data.get('webhook_secret'):
                    self.set_param('elevenlabs_post_call_webhook_secret',
                                   data['webhook_secret'])
                logger.info("EL post-call webhook created: %s -> %s", webhook_id, url)
            except Exception as e:
                logger.exception("EL post-call webhook create failed: %s", e)
                return
        # Select it as the workspace post-call webhook.
        try:
            rec.get_elevenlabs_client().conversational_ai.settings.update(webhooks={
                "post_call_webhook_id": webhook_id,
                "events": ["transcript"],
                "transcript_format": "json",
                "send_audio": False,
            })
            logger.info("EL post-call webhook selected: %s", webhook_id)
        except Exception as e:
            logger.exception("EL post-call webhook select failed: %s", e)

    def elevenlabs_get_voices(self):
        self.env['connect.elevenlabs_voice'].get_voices()


    def elevenlabs_regenerate_prompts(self):
        self.env['connect.callflow'].elevenlabs_regenerate_prompts()


    def elevenlabs_sync_ai_agents(self):
        self.env['connect.elevenlabs_agent'].sync()


    def elevenlabs_reset_token(self):
        # Generate new token.
        self.set_param('elevenlabs_agent_token', str(uuid.uuid4()))
        self._push_elevenlabs_initiation_webhook()
        self._push_elevenlabs_post_call_webhook()


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
