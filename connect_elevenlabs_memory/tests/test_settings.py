# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRecallConfig(TransactionCase):
    def test_get_recall_config(self):
        # Service connection comes from the memory module (memory.*), the
        # ElevenLabs-specific bits from connect.settings.
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("memory.service_url", "http://memory-svc:8790")
        icp.set_param("memory.token", "svc-tok")
        s = self.env["connect.settings"]
        s.set_param("hindsight_memory_enabled", True)
        cfg = s.get_recall_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["service_url"], "http://memory-svc:8790")
        self.assertEqual(cfg["token"], "svc-tok")
        self.assertEqual(cfg["shared_bank"], "business-knowledge")
