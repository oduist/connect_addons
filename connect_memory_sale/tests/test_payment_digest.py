import json
from datetime import date, timedelta

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestPaymentDigest(TestSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("connect_memory.enabled", "1")
        cls.env["ir.config_parameter"].sudo().set_param("memory_sale.digest_min_invoices", "1")
        cls.env["ir.config_parameter"].sudo().set_param("memory_sale.digest_period_months", "12")
        cls.env["ir.config_parameter"].sudo().set_param("memory_sale.digest_batch_size", "5")

    def test_cron_emits_observation_for_paid_invoices(self):
        partner = self.partner
        for _i in range(2):
            move = self.env["account.move"].create({
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "invoice_date": date.today(),
                "invoice_line_ids": [Command.create({
                    "product_id": self.product_a.id,
                    "price_unit": 800.0,
                    "quantity": 1.0,
                })],
            })
            move.action_post()
            self.env["account.payment.register"].with_context(
                active_model="account.move", active_ids=move.ids
            ).create({})._create_payments()
        partner.memory_payment_digest_date = False
        self.env["res.partner"]._memory_sale_payment_digest()
        rows = self.env["connect.memory.outbox"].sudo().search([
            ("commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("domain", "=", "account"),
        ]).filtered(lambda r: "kind:digest" in (r.payload or ""))
        self.assertTrue(rows, "cron must emit an observation digest")

    def _digest_data(self, partner):
        self.env["res.partner"]._memory_sale_payment_digest()
        rows = self.env["connect.memory.outbox"].sudo().search([
            ("commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("domain", "=", "account"),
        ]).filtered(lambda r: "kind:digest" in (r.payload or ""))
        self.assertTrue(rows, "cron must emit an observation digest")
        return json.loads(rows[-1].payload)["data"]

    def test_late_ratio_capped_with_multiple_partial_payments(self):
        """A single invoice paid in two late installments must count as ONE
        late invoice, not two: late_ratio stays <= 1.0 (regression for the
        old len(days_late)/len(invoices) that could exceed 100%)."""
        partner = self.partner
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_date": date.today() - timedelta(days=40),
            "invoice_date_due": date.today() - timedelta(days=30),
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id,
                "price_unit": 1000.0,
                "quantity": 1.0,
            })],
        })
        move.action_post()
        # two partial payments, both dated today -> both late
        for _i in range(2):
            self.env["account.payment.register"].with_context(
                active_model="account.move", active_ids=move.ids
            ).create({"amount": 400.0})._create_payments()
        partner.memory_payment_digest_date = False
        data = self._digest_data(partner)
        self.assertEqual(data["invoices_count"], 1)
        self.assertEqual(data["late_count"], 1, "one late invoice, not two payments")
        self.assertLessEqual(data["late_ratio"], 1.0, "ratio must not exceed 100%")
        self.assertEqual(data["late_ratio"], 1.0)
