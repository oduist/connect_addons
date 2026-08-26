# -*- coding: utf-8 -*-
import json
from unittest.mock import patch, MagicMock
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestRecallController(HttpCase):
    def setUp(self):
        super().setUp()
        s = self.env["connect.settings"]
        s.set_param("memory_service_url", "http://memory-svc:8790")
        s.set_param("memory_service_token", "svc-tok")
        s.set_param("elevenlabs_agent_token", "tok123")
        s.set_param("hindsight_memory_enabled", True)
        company = self.env["res.partner"].create({"name": "Acme", "is_company": True})
        self.call = self.env["connect.call"].create(
            {"partner": company.id, "caller": "+15551230000"})

    def _post(self, token):
        return self.url_open(
            "/connect_elevenlabs/memory/recall",
            data=json.dumps({"query": "who is this", "call_id": self.call.id}),
            headers={"Content-Type": "application/json",
                     "x-elevenlabs-agent-token": token})

    def test_rejects_bad_token(self):
        resp = self._post("wrong")
        self.assertEqual(resp.status_code, 401)

    def test_recall_proxies_to_memory_service(self):
        fake = MagicMock()
        fake.raise_for_status.return_value = None
        fake.json.return_value = {"context": "Bob prefers mornings."}
        with patch(
            "odoo.addons.connect_elevenlabs_memory.controllers.main.requests.post",
            return_value=fake) as post:
            resp = self._post("tok123")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)["context"], "Bob prefers mornings.")
        # It calls the memory service /recall (never Hindsight directly) with the
        # service token and the banks Odoo resolved.
        self.assertTrue(post.called)
        self.assertTrue(post.call_args.args[0].endswith("/recall"))
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["token"], "svc-tok")
        bank = "partner-%s" % self.call.partner.commercial_partner_id.id
        self.assertEqual(sent["banks"], [bank])
