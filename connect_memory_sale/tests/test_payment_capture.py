import json

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestPaymentCapture(TestSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("connect_memory.enabled", "1")

    def _payment_events(self, partner):
        out = []
        for row in self.env["connect.memory.outbox"].sudo().search([
            ("commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("domain", "=", "account"),
        ]):
            payload = json.loads(row.payload) if row.payload else {}
            if "kind:payment" in payload.get("tags", []):
                out.append(payload)
        return out

    def test_reconcile_payment_emits_payment_event(self):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id,
                "price_unit": 1000.0,
                "quantity": 1.0,
            })],
        })
        move.action_post()
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=move.ids
        ).create({})._create_payments()
        events = self._payment_events(self.partner)
        self.assertTrue(events, "reconciliation must emit a payment event")
        self.assertIn("role:customer", events[0]["tags"])
