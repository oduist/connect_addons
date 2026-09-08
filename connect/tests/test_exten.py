# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestExtenNameSearch(TransactionCase):
    """connect.exten.name is computed and not stored, and it is also _rec_name.
    Without a search method every Many2one autocomplete on connect.exten (the
    Extension dropdown of a CallFlow Choice, for one) blows up with
    "Cannot convert connect.exten.name to SQL because it is not stored".
    """

    def setUp(self):
        super().setUp()
        self.exten = self.env["connect.exten"].create({"number": "94271"})

    def test_name_search_matches_the_number(self):
        res = self.env["connect.exten"].name_search("94271")
        self.assertIn(self.exten.id, [r[0] for r in res])

    def test_name_search_is_not_a_prefix_only_match(self):
        res = self.env["connect.exten"].name_search("427")
        self.assertIn(self.exten.id, [r[0] for r in res])

    def test_name_search_empty_value_returns_records(self):
        self.assertTrue(self.env["connect.exten"].name_search(""))

    def test_web_name_search_used_by_the_dropdown(self):
        # What the web client actually calls for a Many2one autocomplete.
        res = self.env["connect.exten"].web_name_search(
            "94271", specification={"display_name": {}})
        self.assertIn(self.exten.id, [r["id"] for r in res])

    def test_negative_operator_still_converts_to_sql(self):
        found = self.env["connect.exten"].search([("name", "not ilike", "94271")])
        self.assertNotIn(self.exten.id, found.ids)

    def test_label_still_renders_number_and_destination(self):
        self.assertEqual(self.exten.name, "94271 <>")
