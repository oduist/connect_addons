import logging

from odoo import api, fields, models, tools

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
    def _memory_emit(self, envelope, module="connect_memory"):
        """Enqueue an event, gated by the master switch and the Connect license
        of the owning module. Domain modules pass their own name (e.g.
        module="connect_memory_sale") so each is enforced by its own license."""
        if not self._memory_enabled():
            return self.env["connect.memory.outbox"]
        if not self._memory_license_ok(module):
            return self.env["connect.memory.outbox"]
        return self.env["connect.memory.outbox"].enqueue(envelope)

    @tools.ormcache("date_key", "module")
    def _memory_license_check_cached(self, date_key, module):
        """Cached Connect-license gate, keyed on (day, module). The day key
        re-evaluates an expiring trial within 24h without an RS256 verify per
        captured event (backfill replays hundreds of thousands of messages);
        the module key enforces each licensed module independently."""
        return self.env["oduist.license"].sudo().check_license(module, silent=True)

    @api.model
    def _memory_license_ok(self, module="connect_memory"):
        """Silent license gate for capture. Never raises: any failure degrades
        to "allow" so capture can never break the host business operation."""
        try:
            return self._memory_license_check_cached(fields.Date.today(), module)
        except Exception:
            return True
