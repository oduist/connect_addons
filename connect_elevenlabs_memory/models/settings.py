# -*- coding: utf-8 -*-
from odoo import models, fields


class ConnectSettings(models.Model):
    _inherit = "connect.settings"

    # ElevenLabs voice-memory recall config only. The Hindsight connection
    # (base URL, tenant, API key) lives in the memory service, never in Odoo:
    # recall reaches that service via the memory module's `connect_memory.service_url`
    # and `connect_memory.token` (see get_recall_config).
    hindsight_memory_enabled = fields.Boolean(string="ElevenLabs Voice Memory")

    def get_recall_config(self):
        """Config for the live recall tool: the ElevenLabs enable toggle from
        connect.settings + the memory-service connection from the memory module
        (connect_memory.service_url / connect_memory.token)."""
        get = self.sudo().get_param
        icp = self.env["ir.config_parameter"].sudo()
        return {
            "enabled": bool(get("hindsight_memory_enabled")),
            "service_url": icp.get_param("connect_memory.service_url") or "",
            "token": icp.get_param("connect_memory.token") or "",
        }
