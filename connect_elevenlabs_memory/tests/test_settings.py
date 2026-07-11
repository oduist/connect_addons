# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRecallConfig(TransactionCase):
    def test_get_recall_config(self):
        # Service connection comes from the memory module (memory.*), the
        # ElevenLabs-specific bits from connect.settings.
        s = self.env["connect.settings"]
        s.set_param("memory_service_url", "http://memory-svc:8790")
        s.set_param("memory_service_token", "svc-tok")
        s.set_param("hindsight_memory_enabled", True)
        cfg = s.get_recall_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["service_url"], "http://memory-svc:8790")
        self.assertEqual(cfg["token"], "svc-tok")
