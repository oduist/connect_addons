# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPersonalBank(TransactionCase):
    def test_bank_from_partner_uses_commercial(self):
        company = self.env["res.partner"].create({"name": "Acme", "is_company": True})
        contact = self.env["res.partner"].create({"name": "Bob", "parent_id": company.id})
        call = self.env["connect.call"].create({"partner": contact.id, "caller": "+15551230000"})
        self.assertEqual(call._hindsight_personal_bank(), "partner-%s" % company.id)

    def test_bank_fallback_to_caller_number(self):
        call = self.env["connect.call"].create({"caller": "+15559990000"})
        self.assertEqual(call._hindsight_personal_bank(), "whatsapp-+15559990000")

    def test_bank_false_when_no_partner_no_caller(self):
        call = self.env["connect.call"].create({"caller": False})
        self.assertFalse(call._hindsight_personal_bank())
