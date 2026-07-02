# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRouting(TransactionCase):
    def test_creates_extension_for_number_pointing_at_agent(self):
        sender = self.env["connect.whatsapp_sender"].create({"number": "+15557778888"})
        # The helper only uses agent.id; use a placeholder recordset to avoid
        # creating a full ElevenLabs agent (which needs the API + a license).
        agent = self.env["connect.elevenlabs_agent"].browse(4242)
        exten = sender.action_route_calls_to_agent(agent)
        self.assertEqual(exten.number, "+15557778888")
        self.assertEqual(exten.model, "connect.elevenlabs_agent")
        self.assertEqual(exten.res_id, 4242)

    def test_route_is_idempotent(self):
        sender = self.env["connect.whatsapp_sender"].create({"number": "+15550001111"})
        agent = self.env["connect.elevenlabs_agent"].browse(4242)
        first = sender.action_route_calls_to_agent(agent)
        second = sender.action_route_calls_to_agent(agent)
        self.assertEqual(first, second)
        self.assertEqual(
            self.env["connect.exten"].search_count([("number", "=", "+15550001111")]), 1)
