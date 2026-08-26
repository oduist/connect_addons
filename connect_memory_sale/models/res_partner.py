import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    memory_payment_digest_date = fields.Datetime(
        string="Last Payment Digest", copy=False, index=True,
        help="Cursor: last time the payment-behavior digest was computed for this partner.")

    @api.model
    def _memory_sale_payment_digest(self):
        """Cron-driven: compute payment-behavior observation for a batch of
        commercial partners whose digest is stale (> 7 days old or never run).
        Emits a memory event kind=observation per partner into connect.memory.outbox."""
        mixin = self.env["connect.memory.sale.mixin"]
        if not self.env["connect.memory.mixin"]._memory_enabled():  # master switch
            return
        ICP = self.env["ir.config_parameter"].sudo()
        months = int(ICP.get_param("connect_memory_sale.digest_period_months", "6") or 6)
        min_inv = int(ICP.get_param("connect_memory_sale.digest_min_invoices", "3") or 3)
        batch = int(ICP.get_param("connect_memory_sale.digest_batch_size", "50") or 50)
        week_ago = fields.Datetime.now() - timedelta(days=7)
        date_from = fields.Date.context_today(self) - relativedelta(months=months)
        company_currency = self.env.company.currency_id
        # find commercial partners that HAVE paid invoices in the period,
        # then keep only those whose digest cursor is stale
        Move = self.env["account.move"]
        paid_moves = Move.search([
            ("move_type", "in", ("out_invoice", "out_refund")),
            ("state", "=", "posted"),
            ("payment_state", "in", ("paid", "in_payment", "partial")),
            ("date", ">=", date_from),
        ])
        partner_ids = set(paid_moves.mapped("commercial_partner_id").ids)
        if not partner_ids:
            return
        thread = self.env["mail.thread"]
        partners = self.browse(partner_ids).filtered(
            lambda p: (not p.memory_payment_digest_date
                       or p.memory_payment_digest_date < week_ago)
            and thread._memory_is_external(p)
        )[:batch]
        if not partners:
            return
        for partner in partners:
            invoices = Move.search([
                ("commercial_partner_id", "=", partner.id),
                ("move_type", "in", ("out_invoice", "out_refund")),
                ("state", "=", "posted"),
                ("payment_state", "in", ("paid", "in_payment", "partial")),
                ("date", ">=", date_from),
            ])
            if len(invoices) < min_inv:
                partner.memory_payment_digest_date = fields.Datetime.now()
                continue
            total = sum(invoices.mapped("amount_total_signed"))
            days_late = []          # per-payment lateness, feeds avg/max
            late_invoices = 0       # invoices with at least one late payment
            for inv in invoices:
                inv_late = False
                for pay in inv._get_reconciled_payments():
                    if inv.invoice_date_due and pay.date and pay.date > inv.invoice_date_due:
                        days_late.append((pay.date - inv.invoice_date_due).days)
                        inv_late = True
                if inv_late:
                    late_invoices += 1
            avg_late = round(sum(days_late) / len(days_late)) if days_late else 0
            max_late = max(days_late) if days_late else 0
            ratio = late_invoices / len(invoices) if invoices else 0.0
            late_pct = round(ratio * 100)
            text = ("%s: %d invoices in %d months (%g %s). "
                    "Avg %d days late, %d%% paid late%s.") % (
                partner.display_name, len(invoices), months, total,
                company_currency.name, avg_late, late_pct,
                ", max %d days" % max_late if max_late else "")
            tags = mixin._memory_sale_base_tags("account", "customer", partner.id) \
                + ["signal:late_payment", "kind:digest"]
            envelope = mixin._memory_sale_build(
                domain="account", kind="observation",
                scope={"commercial_partner_id": partner.id,
                       "commercial_partner_name": partner.display_name},
                source={"system": "odoo", "db": self.env.cr.dbname,
                        "model": "connect.memory.sale.payment.digest"},
                text=text, tags=tags, sensitivity="financial",
                dedup_key="payment-digest-%s-%sW%s" % (
                    partner.id, *fields.Date.context_today(self).isocalendar()[:2]),
                data={"period_months": months,
                      "invoices_count": len(invoices),
                      "total_amount_company_currency": total,
                      "currency": company_currency.name,
                      "avg_days_late": avg_late,
                      "max_days_late": max_late,
                      "late_count": late_invoices,
                      "late_ratio": ratio})
            self.env["connect.memory.mixin"]._memory_emit(envelope, module="connect_memory_sale")
            partner.memory_payment_digest_date = fields.Datetime.now()
