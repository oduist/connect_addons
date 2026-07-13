import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import MemoryCommon


@tagged("post_install", "-at_install")
class TestOutbox(MemoryCommon):
    """The engine-neutral outbox contract: enqueue idempotency, the pull/ack
    endpoints' model layer, and the retention vacuum."""

    def _envelope(self, **override):
        envelope = {
            "event_id": str(uuid.uuid4()),
            "dedup_key": "src-1",
            "content_hash": "sha256:aaa",
            "domain": "partner",
            "kind": "message",
            "scope": {"commercial_partner_id": self.customer.id},
            "source": {"company_id": self.env.company.id},
            "text": "hello",
        }
        envelope.update(override)
        return envelope

    def test_enqueue_is_idempotent_on_dedup_and_hash(self):
        outbox = self.env["connect.memory.outbox"]
        first = outbox.enqueue(self._envelope())
        second = outbox.enqueue(self._envelope())
        self.assertEqual(first.id, second.id,
                         "an identical event must not create a second row")

    def test_enqueue_content_edit_creates_new_row(self):
        outbox = self.env["connect.memory.outbox"]
        first = outbox.enqueue(self._envelope())
        edited = outbox.enqueue(self._envelope(content_hash="sha256:bbb"))
        self.assertNotEqual(first.id, edited.id,
                            "a changed content_hash (edit) must create a new row")

    def test_enqueue_maps_scope_and_source(self):
        row = self.env["connect.memory.outbox"].enqueue(self._envelope())
        self.assertEqual(row.commercial_partner_id, self.customer)
        self.assertEqual(row.company_id, self.env.company)
        self.assertEqual(row.state, "pending")

    def test_content_hash_is_stable_and_prefixed(self):
        outbox = self.env["connect.memory.outbox"]
        digest = outbox._memory_content_hash("x")
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(digest, outbox._memory_content_hash("x"))

    def test_fetch_batch_returns_only_pending_with_shape(self):
        outbox = self.env["connect.memory.outbox"]
        row = outbox.enqueue(self._envelope())
        batch = outbox.fetch_batch(limit=100)
        item = next((r for r in batch if r["id"] == row.id), None)
        self.assertIsNotNone(item, "pending events must be pullable")
        self.assertEqual(set(item), {"id", "event_id", "domain", "kind", "payload"})
        self.assertIsInstance(item["payload"], dict)

    def test_fetch_batch_domain_filter(self):
        outbox = self.env["connect.memory.outbox"]
        partner = outbox.enqueue(self._envelope(dedup_key="d-p", domain="partner"))
        sale = outbox.enqueue(self._envelope(dedup_key="d-s", domain="sale"))
        ids = [r["id"] for r in outbox.fetch_batch(domain="partner")]
        self.assertIn(partner.id, ids)
        self.assertNotIn(sale.id, ids)

    def test_fetch_batch_engine_filter(self):
        outbox = self.env["connect.memory.outbox"]
        neutral = outbox.enqueue(self._envelope(dedup_key="e-none"))
        cognee = outbox.enqueue(self._envelope(dedup_key="e-c", engine="cognee"))
        hindsight_ids = [r["id"] for r in outbox.fetch_batch(engine="hindsight")]
        self.assertIn(neutral.id, hindsight_ids,
                      "engine-neutral events go to every engine")
        self.assertNotIn(cognee.id, hindsight_ids,
                         "a cognee-only event is hidden from hindsight")
        self.assertIn(cognee.id, [r["id"] for r in outbox.fetch_batch(engine="cognee")])

    def test_ack_ok_marks_sent(self):
        outbox = self.env["connect.memory.outbox"]
        row = outbox.enqueue(self._envelope())
        self.assertEqual(outbox.ack([row.id], ok=True), 1)
        self.assertEqual(row.state, "sent")
        self.assertTrue(row.sent_at)

    def test_ack_failure_records_error_and_attempts(self):
        outbox = self.env["connect.memory.outbox"]
        row = outbox.enqueue(self._envelope())
        outbox.ack([row.id], ok=False, error="boom")
        self.assertEqual(row.state, "failed")
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.last_error, "boom")

    def test_retention_vacuum_drops_payload_keeps_tombstone(self):
        outbox = self.env["connect.memory.outbox"]
        row = outbox.enqueue(self._envelope())
        row.write({"state": "sent",
                   "sent_at": fields.Datetime.now() - timedelta(days=999)})
        self.assertGreaterEqual(outbox._cron_vacuum_sent(days=7), 1)
        self.assertFalse(row.payload, "the bulky payload must be cleared")
        self.assertTrue(row.dedup_key and row.content_hash,
                        "a de-dup tombstone must survive")
        self.assertEqual(row.state, "sent")

    def test_retention_keeps_recent_and_respects_disable(self):
        outbox = self.env["connect.memory.outbox"]
        recent = outbox.enqueue(self._envelope())
        recent.write({"state": "sent", "sent_at": fields.Datetime.now()})
        self.assertEqual(outbox._cron_vacuum_sent(days=7), 0,
                         "a recently sent row must survive")
        self.assertTrue(recent.payload)
        old = outbox.enqueue(self._envelope(dedup_key="old"))
        old.write({"state": "sent",
                   "sent_at": fields.Datetime.now() - timedelta(days=999)})
        self.assertEqual(outbox._cron_vacuum_sent(days=0), 0,
                         "days=0 disables retention entirely")
        self.assertTrue(old.payload)
