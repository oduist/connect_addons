from odoo import fields, models

from odoo.addons.connect.models.license import ODUIST_MODULES

# Register the base module in Connect's licensed-module registry. Domain
# modules (connect_memory_sale, ...) append their own name the same way.
if "connect_memory" not in ODUIST_MODULES:
    ODUIST_MODULES.append("connect_memory")


class ConnectSettings(models.Model):
    _inherit = "connect.settings"

    memory_enabled = fields.Boolean(
        string="Enable memory capture",
        help="When on, customer correspondence is captured into "
             "connect.memory.outbox.")
    memory_service_url = fields.Char(string="Memory service URL")
    memory_service_token = fields.Char(string="Memory service token")
    memory_default_engine = fields.Char(
        string="Default engine", default="hindsight")
    memory_outbox_retention_days = fields.Integer(
        string="Outbox retention (days)", default=7,
        help="Daily cron vacuums the payload of sent outbox rows older than "
             "this, keeping a thin de-dup tombstone. 0 = keep payloads.")

    def open_memory_form(self):
        rec = self.search([])
        if not rec:
            rec = self.sudo().with_context(no_constrains=True).create({})
        else:
            rec = rec[0]
        return {
            "type": "ir.actions.act_window",
            "res_model": "connect.settings",
            "res_id": rec.id,
            "name": "Memory",
            "view_mode": "form",
            "view_id": self.env.ref(
                "connect_memory.connect_memory_settings_form").id,
            "target": "current",
        }

    def action_open_memory_backfill(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Backfill all partners",
            "res_model": "connect.memory.backfill.wizard",
            "view_mode": "form",
            "target": "new",
        }
