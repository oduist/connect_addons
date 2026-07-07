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

    def _post_call_payload(self, caller):
        return {
            "conversation_id": "conv-test-1",
            "agent_id": "agent_uid_test",
            "metadata": {
                "call_duration_secs": 42,
                "phone_call": {
                    "external_number": caller,
                    "agent_number": "+13105550111",
                    "call_sid": "CAtest1",
                },
            },
            "analysis": {
                "call_successful": "success",
                "transcript_summary": "Booked a demo.",
            },
            "transcript": [
                {"role": "agent", "message": "Hi, how can I help?"},
                {"role": "user", "message": "Book a demo please."},
                {"role": "agent", "message": ""},
            ],
        }

    def test_inbound_ingestion_creates_recording_and_retains(self):
        """EL post-call ingestion -> connect.recording -> memory retain fires."""
        self.env["ir.config_parameter"].sudo().set_param("memory.enabled", "True")
        caller = "+13105550100"
        partner = self.env["res.partner"].create(
            {"name": "Caller Co", "is_company": True, "phone": caller})
        # Sanity: caller must resolve to the partner for retain to have a bank.
        self.assertEqual(
            self.env["res.partner"].get_partner_by_number(caller), partner)

        call = self.env["connect.call"].create_from_elevenlabs_inbound(
            self._post_call_payload(caller))

        recording = self.env["connect.recording"].search([("call", "=", call.id)])
        self.assertEqual(len(recording), 1, "ingestion should create one recording")
        self.assertEqual(
            recording.elevenlabs_transcript,
            "agent: Hi, how can I help?\nuser: Book a demo please.",
            "empty turns are dropped; role: message lines are joined")
        row = self._outbox_row(recording)
        self.assertTrue(row, "retain should enqueue for the ingested recording")
        self.assertEqual(row.commercial_partner_id.id, partner.id)

    def test_inbound_ingestion_is_idempotent(self):
        """Duplicate EL post-call delivery must not double-ingest."""
        self.env["ir.config_parameter"].sudo().set_param("memory.enabled", "True")
        payload = self._post_call_payload("+13105550100")
        first = self.env["connect.call"].create_from_elevenlabs_inbound(payload)
        second = self.env["connect.call"].create_from_elevenlabs_inbound(payload)
        self.assertEqual(first, second, "same conversation_id returns same call")
        self.assertEqual(
            len(self.env["connect.recording"].search([("call", "=", first.id)])),
            1, "no duplicate recording on redelivery")
