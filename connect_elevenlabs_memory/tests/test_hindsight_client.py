# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.addons.connect_elevenlabs_memory.models import hindsight_client as hc


@tagged("post_install", "-at_install")
class TestHindsightClient(TransactionCase):
    def test_reflect_request_shape(self):
        url, headers, body = hc.build_reflect_request(
            "https://api.hindsight.vectorize.io/", "default", "hsk_x",
            "partner-42", "who is calling?")
        self.assertEqual(
            url, "https://api.hindsight.vectorize.io/v1/default/banks/partner-42/reflect")
        self.assertEqual(headers["Authorization"], "Bearer hsk_x")
        self.assertEqual(body["query"], "who is calling?")
        self.assertEqual(body["budget"], "low")
        self.assertEqual(body["max_tokens"], 300)

    def test_parse_reflect_response_variants(self):
        self.assertEqual(hc.parse_reflect_response({"answer": " hi "}), "hi")
        self.assertEqual(hc.parse_reflect_response({"text": "t"}), "t")
        self.assertEqual(hc.parse_reflect_response({"result": "r"}), "r")
        self.assertEqual(hc.parse_reflect_response({}), "")
        self.assertEqual(hc.parse_reflect_response(None), "")

    def test_retain_request_shape(self):
        url, headers, body = hc.build_retain_request(
            "https://api.hindsight.vectorize.io", "default", "hsk_x",
            "partner-42", "call summary", document_id="connect-recording-7")
        self.assertEqual(
            url, "https://api.hindsight.vectorize.io/v1/default/banks/partner-42/memories")
        self.assertEqual(body["async"], False)
        self.assertEqual(body["items"][0]["content"], "call summary")
        self.assertEqual(body["items"][0]["document_id"], "connect-recording-7")
        self.assertEqual(body["items"][0]["context"], "voice/call")
