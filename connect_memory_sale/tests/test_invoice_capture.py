import json

from odoo import fields
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestInvoiceCapture(TestSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("connect_memory.enabled", "1")

    def _account_payloads(self, partner, tag=None):
        rows = self.env["connect.memory.outbox"].sudo().search([
            ("commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("domain", "=", "account"),
        ])
        out = []
        for row in rows:
            payload = json.loads(row.payload) if row.payload else {}
            if tag is None or tag in payload.get("tags", []):
                out.append(payload)
        return out

    def test_post_invoice_emits_lifecycle(self):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id,
                "price_unit": 500.0,
                "quantity": 2.0,
            })],
        })
        move.action_post()
        events = self._account_payloads(self.partner)
        self.assertTrue(events, "action_post must emit an account lifecycle event")
        self.assertIn("move_type:out_invoice", events[0]["tags"])

    def test_refund_tagged_as_customer_refund(self):
        move = self.env["account.move"].create({
            "move_type": "out_refund",
            "partner_id": self.partner.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id,
                "price_unit": 100.0,
                "quantity": 1.0,
            })],
        })
        move.action_post()
        events = self._account_payloads(self.partner, tag="move_type:out_refund")
        self.assertTrue(events, "credit note must emit a lifecycle event")
        self.assertIn("role:customer", events[0]["tags"])

    def test_vendor_bill_tagged_as_vendor(self):
        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id,
                "price_unit": 100.0,
                "quantity": 1.0,
            })],
        })
        move.action_post()
        events = self._account_payloads(self.partner, tag="move_type:in_invoice")
        self.assertTrue(events, "vendor bill must emit a lifecycle event")
        self.assertIn("role:vendor", events[0]["tags"])

    def test_own_company_partner_invoice_emits_nothing(self):
        """Invoice posting now applies the external-partner gate: an invoice to
        our own company must not be captured."""
        own = self.env.company.partner_id
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": own.id,
            "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({
                "product_id": self.product_a.id,
                "price_unit": 100.0,
                "quantity": 1.0,
            })],
        })
        move.action_post()
        self.assertFalse(self._account_payloads(own),
                         "own-company partner invoice must not be captured")
