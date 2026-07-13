from odoo.tests import tagged

from .common import MemoryCommon


@tagged("post_install", "-at_install")
class TestInbox(MemoryCommon):
    """The question/answer contract: Odoo submits a request, the external
    service claims it and writes the answer back."""

    def test_submit_creates_pending_request(self):
        inbox = self.env["connect.memory.inbox"]
        request = inbox.submit(
            query="What do we know about Alice?", query_type="recall",
            scope={"commercial_partner_id": self.customer.id},
            res_model="res.partner", res_id=self.customer.id, engine="hindsight")
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.query_type, "recall")
        self.assertEqual(request.commercial_partner_id, self.customer)
        self.assertTrue(request.request, "a JSON request envelope must be stored")

    def test_claim_batch_moves_to_processing_and_carries_query(self):
        inbox = self.env["connect.memory.inbox"]
        request = inbox.submit(query="ship status?")
        claimed = inbox.claim_batch(limit=50)
        self.assertEqual(request.state, "processing")
        item = next((c for c in claimed if c["id"] == request.id), None)
        self.assertIsNotNone(item)
        self.assertEqual(item["request"].get("query"), "ship status?")

    def test_store_answer_extracts_text_from_dict(self):
        inbox = self.env["connect.memory.inbox"]
        request = inbox.submit(query="q")
        self.assertTrue(
            inbox.store_answer(request.id, {"text": "Alice is a VIP", "score": 0.9}))
        self.assertEqual(request.answer_text, "Alice is a VIP")
        self.assertEqual(request.state, "done")
        self.assertTrue(request.done_at)

    def test_store_answer_answer_key_and_plain_string(self):
        inbox = self.env["connect.memory.inbox"]
        by_key = inbox.submit(query="q1")
        inbox.store_answer(by_key.id, {"answer": "from answer key"})
        flat = inbox.submit(query="q2")
        inbox.store_answer(flat.id, "a flat string")
        self.assertEqual(by_key.answer_text, "from answer key")
        self.assertEqual(flat.answer_text, "a flat string")

    def test_store_answer_failure_and_unknown_id(self):
        inbox = self.env["connect.memory.inbox"]
        request = inbox.submit(query="q")
        inbox.store_answer(request.id, {"error": "nope"}, ok=False)
        self.assertEqual(request.state, "failed")
        self.assertFalse(inbox.store_answer(999999999, {"text": "x"}),
                         "an unknown id must return False, not raise")

    def test_partner_summary_action_queues_reflect(self):
        action = self.customer.action_memory_summary()
        request = self.env["connect.memory.inbox"].browse(action["res_id"])
        self.assertEqual(request.query_type, "reflect")
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.commercial_partner_id, self.customer)
        self.assertEqual(request.res_model, "res.partner")
        self.assertEqual(request.res_id, self.customer.id)
