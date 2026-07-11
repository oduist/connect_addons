import json

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestSaleCapture(TestSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("connect_memory.enabled", "1")

    def _outbox_for(self, commercial_partner):
        return self.env["connect.memory.outbox"].sudo().search([
            ("commercial_partner_id", "=", commercial_partner.id),
        ])

    def _payloads(self, partner, **filters):
        rows = self._outbox_for(partner.commercial_partner_id)
        out = []
        for row in rows:
            payload = json.loads(row.payload) if row.payload else {}
            if all(t in payload.get("tags", []) for t in filters.pop("tags", [])):
                out.append(payload)
            elif not filters:
                out.append(payload)
        return out

    def _make_so(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_uom_qty": 5.0,
                "price_unit": 100.0,
            })],
        })

    def test_create_order_emits_created_event(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_uom_qty": 10.0,
                "price_unit": 100.0,
            })],
        })
        events = self._payloads(self.partner, tags=["domain:sale"])
        created = [e for e in events if e.get("kind") == "created"]
        self.assertTrue(created, "create() must emit a sale 'created' event")
        self.assertIn("role:customer", created[0]["tags"])

    def test_confirm_emits_lifecycle_confirmed(self):
        order = self._make_so()
        order.action_confirm()
        events = self._payloads(self.partner, tags=["outcome:confirmed"])
        self.assertTrue(events)

    def test_cancel_emits_lifecycle_cancelled(self):
        order = self._make_so()
        order.action_confirm()
        order.action_cancel()
        events = self._payloads(self.partner, tags=["outcome:cancelled"])
        self.assertTrue(events)

    def test_lock_emits_lifecycle_locked(self):
        order = self._make_so()
        order.action_confirm()
        order.action_lock()
        events = self._payloads(self.partner, tags=["outcome:locked"])
        self.assertTrue(events)

    def test_state_change_after_confirm_emits_diff(self):
        order = self._make_so()
        order.action_confirm()
        # clear outbox so only the edit shows
        self.env["connect.memory.outbox"].sudo().search([("state", "=", "pending")]).unlink()
        line = order.order_line[0]
        order.write({"order_line": [Command.update(line.id, {"product_uom_qty": 99.0})]})
        events = self._payloads(self.partner)
        change = [e for e in events if e.get("kind") == "state_change"]
        self.assertTrue(change, "qty edit on confirmed order must emit state_change")

    def test_state_change_records_real_old_line_value(self):
        order = self._make_so()  # qty 5.0
        order.action_confirm()
        self.env["connect.memory.outbox"].sudo().search([("state", "=", "pending")]).unlink()
        line = order.order_line[0]
        order.write({"order_line": [Command.update(line.id, {"product_uom_qty": 99.0})]})
        change = [e for e in self._payloads(self.partner) if e.get("kind") == "state_change"]
        self.assertTrue(change)
        line_changes = change[0]["data"]["changes"]["order_line"][0]["changes"]
        self.assertEqual(
            line_changes["product_uom_qty"], [5.0, 99.0],
            "diff must carry the real old value, not the post-write value")

    def test_disabled_master_switch_emits_nothing(self):
        self.env["ir.config_parameter"].sudo().set_param("connect_memory.enabled", "0")
        self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_uom_qty": 3.0,
                "price_unit": 100.0,
            })],
        })
        created = [e for e in self._payloads(self.partner, tags=["domain:sale"])
                   if e.get("kind") == "created"]
        self.assertFalse(created, "no event must be emitted when connect_memory.enabled=0")

    def test_should_capture_gate(self):
        """The shared gate: capture only for a real external party, and only
        while the master switch is on."""
        Mix = self.env["connect.memory.sale.mixin"]
        own = self.env.company.partner_id  # our own company -> not external
        self.assertTrue(Mix._memory_sale_should_capture(self.partner))
        self.assertFalse(Mix._memory_sale_should_capture(own), "own company excluded")
        self.assertFalse(Mix._memory_sale_should_capture(self.env["res.partner"]),
                         "empty partner excluded")
        self.env["ir.config_parameter"].sudo().set_param("connect_memory.enabled", "0")
        self.assertFalse(Mix._memory_sale_should_capture(self.partner),
                         "switch off -> never capture")

    def test_own_company_partner_emits_nothing(self):
        """An order to our own company is not an external customer -> no event
        (previously the state_change path also leaked these)."""
        own = self.env.company.partner_id
        order = self.env["sale.order"].create({
            "partner_id": own.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "product_uom_qty": 5.0,
                "price_unit": 100.0,
            })],
        })
        order.action_confirm()
        order.write({"order_line": [Command.update(
            order.order_line[0].id, {"product_uom_qty": 9.0})]})
        self.assertFalse(self._outbox_for(own.commercial_partner_id),
                         "own-company partner must never be captured")
