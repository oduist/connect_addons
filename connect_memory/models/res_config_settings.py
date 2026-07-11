from odoo import fields, models

from odoo.addons.connect.models.license import ODUIST_MODULES

# Register the base module in Connect's licensed-module registry. Domain
# modules (connect_memory_sale, ...) append their own name the same way.
if "connect_memory" not in ODUIST_MODULES:
    ODUIST_MODULES.append("connect_memory")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def action_open_memory_backfill(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Backfill all partners",
            "res_model": "connect.memory.backfill.wizard",
            "view_mode": "form",
            "target": "new",
        }

    memory_enabled = fields.Boolean(
        string="Enable memory capture",
        config_parameter="connect_memory.enabled",
        help="When on, customer correspondence is captured into connect.memory.outbox.")
    memory_service_url = fields.Char(
        string="Memory service URL",
        config_parameter="connect_memory.service_url")
    memory_service_token = fields.Char(
        string="Memory service token",
        config_parameter="connect_memory.token")
    memory_default_engine = fields.Char(
        string="Default engine",
        config_parameter="connect_memory.default_engine")
    memory_outbox_retention_days = fields.Integer(
        string="Outbox retention (days)",
        config_parameter="connect_memory.outbox_retention_days",
        help="Daily cron vacuums the payload of sent outbox rows older than "
             "this, keeping a thin de-dup tombstone. 0 = keep payloads.")
