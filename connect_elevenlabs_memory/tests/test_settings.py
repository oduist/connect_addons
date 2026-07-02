# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHindsightSettings(TransactionCase):
    def test_get_hindsight_config_defaults_and_overrides(self):
        settings = self.env["connect.settings"]
        settings.set_param("hindsight_api_key", "hsk_secret")
        settings.set_param("hindsight_memory_enabled", True)
        cfg = settings.get_hindsight_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["api_key"], "hsk_secret")
        self.assertEqual(cfg["base"], "https://api.hindsight.vectorize.io")
        self.assertEqual(cfg["tenant"], "default")
        self.assertEqual(cfg["shared_bank"], "business-knowledge")
