# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRetain(TransactionCase):
    def _make_recording(self, sid, partner, summary="Booked a demo.",
                        transcript="agent: hi\nuser: book a demo"):
        return self.env["connect.recording"].with_context(
            skip_transcription=True).create({
                "sid": sid,
                "call_sid": sid + "-chan",
                "partner": partner.id,
                "elevenlabs_summary": summary,
                "elevenlabs_transcript": transcript,
            })

    def _outbox_row(self, rec):
        return self.env["memory.outbox"].search(
            [("dedup_key", "=", "connect-recording-%s" % rec.id)], limit=1)

    def test_retain_enqueues_to_outbox(self):
        self.env["ir.config_parameter"].sudo().set_param("memory.enabled", "True")
        company = self.env["res.partner"].create({"name": "Acme", "is_company": True})
        rec = self._make_recording("rec-test-1", company)
        row = self._outbox_row(rec)
        self.assertTrue(row, "retain should enqueue a memory.outbox row")
        self.assertEqual(row.commercial_partner_id.id, company.id)
        self.assertEqual(row.domain, "voice")

    def test_no_retain_when_disabled(self):
        self.env["ir.config_parameter"].sudo().set_param("memory.enabled", "False")
        company = self.env["res.partner"].create({"name": "Acme2", "is_company": True})
        rec = self._make_recording("rec-test-2", company, summary="x", transcript="")
        self.assertFalse(self._outbox_row(rec))
