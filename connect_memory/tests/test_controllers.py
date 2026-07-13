import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMemoryEndpoints(HttpCase):
    """The token-protected JSON-RPC contract used by the external memory
    service to pull events, ack them, claim requests and write answers back."""

    TOKEN = "test-token-123"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = cls.env["connect.settings"].sudo()
        settings.set_param("memory_enabled", True)
        settings.set_param("memory_service_token", cls.TOKEN)
        cls.customer = cls.env["res.partner"].create({
            "name": "Umbrella Corp", "is_company": True})

    def _call(self, path, params, token_header=None):
        headers = {"Content-Type": "application/json"}
        if token_header:
            headers["X-Memory-Token"] = token_header
        body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": params})
        response = self.url_open(path, data=body.encode(), headers=headers)
        response.raise_for_status()
        return response.json().get("result")

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    def test_outbox_fetch_requires_token(self):
        self.assertEqual(
            self._call("/connect_memory/outbox/fetch", {"limit": 5}),
            {"error": "unauthorized"})

    def test_outbox_fetch_rejects_wrong_token(self):
        self.assertEqual(
            self._call("/connect_memory/outbox/fetch", {"limit": 5},
                       token_header="nope"),
            {"error": "unauthorized"})

    # ------------------------------------------------------------------
    # outbox pull + ack round-trip
    # ------------------------------------------------------------------
    def test_outbox_fetch_and_ack_roundtrip(self):
        row = self.env["connect.memory.outbox"].sudo().enqueue({
            "event_id": "evt-http-1", "dedup_key": "http-1",
            "content_hash": "sha256:h", "domain": "partner", "kind": "message",
            "scope": {"commercial_partner_id": self.customer.id}, "text": "hi",
        })
        result = self._call("/connect_memory/outbox/fetch", {"limit": 100},
                            token_header=self.TOKEN)
        self.assertIn(row.id, [e["id"] for e in result["events"]])
        acked = self._call("/connect_memory/outbox/ack",
                           {"token": self.TOKEN, "ids": [row.id], "ok": True})
        self.assertEqual(acked, {"acked": 1})
        self.env.invalidate_all()
        self.assertEqual(row.state, "sent")

    # ------------------------------------------------------------------
    # inbox claim + answer round-trip
    # ------------------------------------------------------------------
    def test_inbox_answer_requires_id(self):
        self.assertEqual(
            self._call("/connect_memory/inbox/answer",
                       {"token": self.TOKEN, "answer": "x"}),
            {"error": "missing id"})

    def test_inbox_claim_and_answer_roundtrip(self):
        request = self.env["connect.memory.inbox"].sudo().submit(query="ship status?")
        claimed = self._call("/connect_memory/inbox/fetch",
                             {"token": self.TOKEN, "limit": 50})
        self.assertIn(request.id, [r["id"] for r in claimed["requests"]])
        self.env.invalidate_all()
        self.assertEqual(request.state, "processing")
        stored = self._call("/connect_memory/inbox/answer",
                            {"token": self.TOKEN, "id": request.id,
                             "answer": {"text": "ships tomorrow"}})
        self.assertEqual(stored, {"stored": True})
        self.env.invalidate_all()
        self.assertEqual(request.state, "done")
        self.assertEqual(request.answer_text, "ships tomorrow")
