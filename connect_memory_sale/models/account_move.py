import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        res = super().action_post()
        if self.env["connect.memory.mixin"]._memory_enabled():
            try:  # capture must never break posting (ADR-009)
                self._memory_sale_capture_posted()
            except Exception:
                _logger.exception("memory_sale: invoice post capture failed")
        return res

    def _memory_sale_capture_posted(self):
        mixin = self.env["connect.memory.sale.mixin"]
        for move in self:
            if move.move_type not in ("out_invoice", "out_refund", "in_invoice", "in_refund"):
                continue
            partner = move.partner_id
            if not mixin._memory_sale_should_capture(partner):
                continue
            role = "vendor" if move.move_type.startswith("in_") else "customer"
            is_refund = "refund" in move.move_type
            label = "Credit Note / Refund" if is_refund else "Invoice"
            due = move.invoice_date_due.isoformat() if move.invoice_date_due else None
            text = "%s %s posted for %s: %g %s due %s." % (
                label, move.name or "", partner.display_name,
                move.amount_total_signed, move.company_id.currency_id.name,
                due or "-")
            tags = mixin._memory_sale_base_tags("account", role, partner.commercial_partner_id.id) \
                + ["move_type:%s" % move.move_type,
                   "via:account.move", "res:account.move-%s" % move.id]
            envelope = mixin._memory_sale_build(
                domain="account", kind="lifecycle",
                scope=mixin._memory_sale_scope(move, partner),
                source=mixin._memory_sale_source(move),
                text=text, tags=tags, sensitivity="financial",
                dedup_key="account.move-%s@posted" % move.id,
                data={"move_type": move.move_type,
                      "amount_total": move.amount_total,
                      "amount_total_signed": move.amount_total_signed,
                      "company_currency": move.company_id.currency_id.name,
                      "invoice_date_due": due,
                      "payment_state": move.payment_state})
            self.env["connect.memory.mixin"]._memory_emit(envelope, module="connect_memory_sale")
