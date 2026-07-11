import hashlib
import uuid

from odoo import api, fields, models

from odoo.addons.connect.models.license import ODUIST_MODULES

# Register connect_memory_sale in Connect's licensed-module registry so it is
# enforced by its own license (mirrors the base module's append).
if "connect_memory_sale" not in ODUIST_MODULES:
    ODUIST_MODULES.append("connect_memory_sale")


class MemorySaleMixin(models.AbstractModel):
    _name = "connect.memory.sale.mixin"
    _description = "Shared envelope builders for memory_sale events"

    @api.model
    def _memory_sale_content_hash(self, text):
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        return "sha256:" + digest

    @api.model
    def _memory_sale_should_capture(self, partner):
        """Single capture gate shared by every memory_sale path: the master
        switch must be on and `partner` must be a real external party (not an
        internal employee, not one of our own companies). Keeps the sale,
        invoice, payment and digest paths consistent."""
        if not partner:
            return False
        if not self.env["connect.memory.mixin"]._memory_enabled():
            return False
        return self.env["mail.thread"]._memory_is_external(partner)

    @api.model
    def _memory_sale_base_tags(self, domain, role, commercial_id):
        return [
            "domain:%s" % domain,
            "role:%s" % role,
            "commercial:%s" % commercial_id,
        ]

    @api.model
    def _memory_sale_build(self, *, domain, kind, scope, source, text,
                           tags, sensitivity, dedup_key,
                           facts=None, data=None):
        """Build a memory event envelope dict (schema: 05-event-model.md)."""
        text = text or ""
        return {
            "event_id": str(uuid.uuid4()),
            "event_version": 1,
            "occurred_at": fields.Datetime.now().isoformat() + "Z",
            "source": source,
            "domain": domain,
            "kind": kind,
            "scope": scope,
            "actor": {"type": "system", "ref": "odoo"},
            "text": text,
            "facts": facts or [],
            "data": data or {},
            "tags": tags,
            "sensitivity": sensitivity,
            "dedup_key": dedup_key,
            "content_hash": self._memory_sale_content_hash(text),
        }

    @api.model
    def _memory_sale_scope(self, record, partner):
        """scope dict from a partner (commercial + optional contact)."""
        commercial = partner.commercial_partner_id or partner
        scope = {
            "commercial_partner_id": commercial.id,
            "commercial_partner_name": commercial.display_name,
        }
        if partner != commercial:
            scope["partner_id"] = partner.id
            scope["partner_name"] = partner.display_name
        return scope

    @api.model
    def _memory_sale_source(self, record):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        record_name = ""
        if "name" in record._fields and record.name:
            record_name = record.name
        elif hasattr(record, "display_name"):
            record_name = record.display_name or ""
        company_id = record.company_id.id if "company_id" in record._fields and record.company_id \
            else self.env.company.id
        return {
            "system": "odoo",
            "db": self.env.cr.dbname,
            "company_id": company_id,
            "model": record._name,
            "res_id": record.id,
            "record_name": record_name,
            "url": "%s/web#id=%s&model=%s" % (base_url, record.id, record._name),
        }
