import logging

from odoo import api, models, tools

_logger = logging.getLogger(__name__)


class MemoryMixin(models.AbstractModel):
    """Reusable helpers for building and emitting memory events. Domain modules
    (memory_crm, memory_sale, ...) use these to keep capture logic DRY."""

    _name = "connect.memory.mixin"
    _description = "Memory event helpers"

    @api.model
    def _memory_scope_for_partner(self, partner):
        """Return (scope dict, commercial partner) for a partner.

        Memory is aggregated by commercial_partner_id (the company); a specific
        contact is carried as partner_id."""
        empty = self.env["res.partner"]
        if not partner:
            return {}, empty
        commercial = partner.commercial_partner_id or partner
        scope = {
            "commercial_partner_id": commercial.id,
            "commercial_partner_name": commercial.display_name,
        }
        if partner != commercial:
            scope["partner_id"] = partner.id
            scope["partner_name"] = partner.display_name
        return scope, commercial

    @api.model
    def _memory_clean_body(self, html_body):
        if not html_body:
            return ""
        return tools.html2plaintext(html_body).strip()

    @api.model
    def _memory_enabled(self):
        """Master capture switch. Single source of truth for the base module
        and every domain module (memory_sale, memory_crm, ...)."""
        return self.env["ir.config_parameter"].sudo().get_param(
            "connect_memory.enabled") in ("1", "True", "true")

    @api.model
    def _memory_emit(self, envelope, module="memory"):
        """Enqueue an event, gated by the master capture switch. The ``module``
        argument is kept for call-site compatibility with domain modules
        (memory_sale, ...) but capture is no longer license-gated here."""
        if not self._memory_enabled():
            return self.env["connect.memory.outbox"]
        return self.env["connect.memory.outbox"].enqueue(envelope)
