# -*- coding: utf-8 -*-
from odoo import models, fields


class ConnectSettings(models.Model):
    _inherit = "connect.settings"

    # ElevenLabs voice-memory recall config only. The Hindsight connection
    # (base URL, tenant, API key) lives in the memory service, never in Odoo:
    # recall reaches that service via the memory module's `memory_service_url`
    # and `memory_service_token` on connect.settings (see get_recall_config).
    hindsight_memory_enabled = fields.Boolean(string="ElevenLabs Voice Memory")

    def get_recall_config(self):
        """Config for the live recall tool: the ElevenLabs enable toggle from
        connect.settings + the memory-service connection from the memory module
        (memory_service_url / memory_service_token)."""
        get = self.sudo().get_param
        return {
            "enabled": bool(get("hindsight_memory_enabled")),
            "service_url": get("memory_service_url") or "",
            "token": get("memory_service_token") or "",
        }
