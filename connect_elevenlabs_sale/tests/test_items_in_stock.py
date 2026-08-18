# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.connect_elevenlabs_sale.controllers.main import (
    ConnectElevenlabsSaleController,
)


@tagged("post_install", "-at_install", "connect_elevenlabs_sale")
class TestItemsInStock(TransactionCase):
    """The agent must report the real on-hand quantity, never a constant."""

    def setUp(self):
        super().setUp()
        self.stock_installed = "qty_available" in self.env["product.template"]._fields

    def _product(self, **vals):
        return self.env["product.template"].create(dict({"name": "Test product"}, **vals))

    def test_storable_product_reports_its_own_quantity(self):
        if not self.stock_installed:
            self.skipTest("stock is not installed in this database")
        product = self._product(is_storable=True)
        self.assertEqual(
            ConnectElevenlabsSaleController._items_in_stock(product),
            product.qty_available,
        )

    def test_quantity_follows_the_product_not_a_constant(self):
        """Two products with different stock must not report the same number."""
        if not self.stock_installed:
            self.skipTest("stock is not installed in this database")
        empty = self._product(name="Empty product", is_storable=True)
        stocked = self._product(name="Stocked product", is_storable=True)
        self.env["stock.quant"].create({
            "product_id": stocked.product_variant_id.id,
            "location_id": self.env.ref("stock.stock_location_stock").id,
            "quantity": 7.0,
        })
        self.assertEqual(ConnectElevenlabsSaleController._items_in_stock(empty), 0.0)
        self.assertEqual(ConnectElevenlabsSaleController._items_in_stock(stocked), 7.0)

    def test_service_has_no_stock(self):
        if not self.stock_installed:
            self.skipTest("stock is not installed in this database")
        service = self._product(type="service", is_storable=False)
        self.assertIsNone(ConnectElevenlabsSaleController._items_in_stock(service))

    def test_no_stock_module_reports_unknown(self):
        """Without the stock module the quantity is unknown, not zero and not ten."""
        if self.stock_installed:
            self.skipTest("stock is installed; this covers the opposite case")
        product = self._product()
        self.assertIsNone(ConnectElevenlabsSaleController._items_in_stock(product))
