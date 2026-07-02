# -*- coding: utf-8 -*-
from unittest.mock import patch
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRetain(TransactionCase):
    def _enable(self):
        s = self.env["connect.settings"]
        s.set_param("hindsight_memory_enabled", True)
        s.set_param("hindsight_api_key", "hsk_x")

    def test_direct_retain_when_memory_absent(self):
        self._enable()
        company = self.env["res.partner"].create({"name": "Acme", "is_company": True})
        with patch("odoo.addons.connect_elevenlabs_memory.models.recording."
                   "ConnectRecording._memory_module_present", return_value=False), \
             patch("odoo.addons.connect_elevenlabs_memory.models.recording."
                   "hindsight_client.retain") as retain:
            self.env["connect.recording"].with_context(skip_transcription=True).create({
                "sid": "rec-test-1",
                "call_sid": "chan-test-1",
                "partner": company.id,
                "elevenlabs_summary": "Booked a demo.",
                "elevenlabs_transcript": "agent: hi\nuser: book a demo",
            })
            self.assertTrue(retain.called)
            # retain(base, tenant, api_key, bank, content, ...) - bank is arg index 3
            self.assertEqual(retain.call_args[0][3], "partner-%s" % company.id)

    def test_no_retain_when_disabled(self):
        company = self.env["res.partner"].create({"name": "Acme2", "is_company": True})
        with patch("odoo.addons.connect_elevenlabs_memory.models.recording."
                   "hindsight_client.retain") as retain:
            self.env["connect.recording"].with_context(skip_transcription=True).create({
                "sid": "rec-test-2",
                "call_sid": "chan-test-2",
                "partner": company.id,
                "elevenlabs_summary": "x",
            })
            self.assertFalse(retain.called)
