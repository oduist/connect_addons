# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMemoryRecallTool(TransactionCase):
    def test_tool_and_params_loaded(self):
        tool = self.env.ref("connect_elevenlabs_memory.agent_tool_memory_recall")
        self.assertEqual(tool.tool_type, "webhook")
        self.assertEqual(tool.path, "/connect_elevenlabs/memory/recall")
        names = tool.params.mapped("name")
        self.assertIn("query", names)
        self.assertIn("call_id", names)
        call_id = tool.params.filtered(lambda p: p.name == "call_id")
        self.assertEqual(call_id.value_type, "dynamic_variable")
        self.assertEqual(call_id.dynamic_variable, "call_id")
        query = tool.params.filtered(lambda p: p.name == "query")
        self.assertEqual(query.value_type, "description")
