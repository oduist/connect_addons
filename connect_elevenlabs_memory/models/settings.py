# -*- coding: utf-8 -*-
from odoo import models, fields


class ConnectSettings(models.Model):
    _inherit = "connect.settings"

    hindsight_memory_enabled = fields.Boolean(string="Hindsight Memory Enabled")
    hindsight_base_url = fields.Char(
        string="Hindsight Base URL", default="https://api.hindsight.vectorize.io")
    hindsight_tenant = fields.Char(string="Hindsight Tenant", default="default")
    hindsight_api_key = fields.Char(
        string="Hindsight API Key", groups="base.group_erp_manager")
    display_hindsight_api_key = fields.Char()
    hindsight_shared_bank = fields.Char(
        string="Shared Knowledge Bank", default="business-knowledge")

    def get_hindsight_config(self):
        get = self.sudo().get_param
        return {
            "enabled": bool(get("hindsight_memory_enabled")),
            "base": get("hindsight_base_url") or "https://api.hindsight.vectorize.io",
            "tenant": get("hindsight_tenant") or "default",
            "api_key": get("hindsight_api_key") or "",
            "shared_bank": get("hindsight_shared_bank") or "business-knowledge",
        }
