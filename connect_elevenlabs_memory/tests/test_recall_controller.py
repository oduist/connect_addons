# -*- coding: utf-8 -*-
import json
from unittest.mock import patch
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestRecallController(HttpCase):
    def setUp(self):
        super().setUp()
        s = self.env["connect.settings"]
        s.set_param("elevenlabs_agent_token", "tok123")
        s.set_param("hindsight_api_key", "hsk_x")
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

    def test_returns_merged_context(self):
        with patch(
            "odoo.addons.connect_elevenlabs_memory.controllers.main.hindsight_client.reflect"
        ) as m:
            m.side_effect = ["Bob prefers mornings.", "We open at 9."]
            resp = self._post("tok123")
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertIn("Bob prefers mornings.", body["context"])
        self.assertIn("We open at 9.", body["context"])
