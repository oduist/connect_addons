import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env["connect.memory.mixin"]._memory_enabled():
            try:  # capture must never break reconciliation (ADR-009)
                records._memory_sale_emit_payment_events()
            except Exception:
                _logger.exception("memory_sale: payment capture failed")
        return records

    def _memory_sale_emit_payment_events(self):
        mixin = self.env["connect.memory.sale.mixin"]
        for partial in self:
            moves = (partial.debit_move_id.move_id | partial.credit_move_id.move_id)
            invoices = moves.filtered(
                lambda m: m.is_invoice(include_receipts=True)
                and m.move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund")
            )
            if not invoices:
                continue
            # prefer a real invoice over a refund when both sides are documents
            invoice = invoices.filtered(
                lambda m: m.move_type in ("out_invoice", "in_invoice"))[:1] \
                or invoices[:1]
            partner = invoice.partner_id
            if not mixin._memory_sale_should_capture(partner):
                continue
            role = "vendor" if invoice.move_type.startswith("in_") else "customer"
            pay_date = partial.max_date
            days_late = 0
            if invoice.invoice_date_due and pay_date and pay_date > invoice.invoice_date_due:
                days_late = (pay_date - invoice.invoice_date_due).days
            doc_label = "Credit note" if "refund" in invoice.move_type else "Invoice"
            late_str = " (%d days late)" % days_late if days_late else ""
            text = "%s %s (%s) received payment %g %s on %s%s." % (
                doc_label, invoice.name or "", partner.display_name,
                partial.amount, partial.company_currency_id.name,
                pay_date, late_str)
            tags = mixin._memory_sale_base_tags(
                "account", role, partner.commercial_partner_id.id) \
                + ["kind:payment", "via:account.partial.reconcile",
                   "res:account.partial.reconcile-%s" % partial.id]
            if days_late:
                tags.append("signal:late_payment")
            envelope = mixin._memory_sale_build(
                domain="account", kind="lifecycle",
                scope=mixin._memory_sale_scope(invoice, partner),
                source=mixin._memory_sale_source(partial),
                text=text, tags=tags, sensitivity="financial",
                dedup_key="account.partial.reconcile-%s" % partial.id,
                data={"amount": partial.amount,
                      "company_currency": partial.company_currency_id.name,
                      "payment_date": pay_date.isoformat() if pay_date else None,
                      "days_late": days_late,
                      "invoice_ref": invoice.name,
                      "invoice_id": invoice.id})
            self.env["connect.memory.mixin"]._memory_emit(envelope, module="memory_sale")
