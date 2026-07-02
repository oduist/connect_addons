# -*- coding: utf-8 -*-
import json
import logging

from werkzeug.exceptions import Unauthorized

from odoo import http

from ..models import hindsight_client

logger = logging.getLogger(__name__)


class ConnectElevenlabsMemoryController(http.Controller):

    def _check_tool_token(self):
        token = http.request.httprequest.headers.get("x-elevenlabs-agent-token")
        expected = http.request.env["connect.settings"].sudo().get_param(
            "elevenlabs_agent_token")
        return bool(token) and bool(expected) and token == expected

    @http.route("/connect_elevenlabs/memory/recall", methods=["POST"],
                type="http", auth="public", csrf=False)
    def recall(self):
        if not self._check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True) or "{}")
        query = data.get("query") or ""
        call_id = data.get("call_id")
        env = http.request.env
        cfg = env["connect.settings"].sudo().get_hindsight_config()
        if not cfg["enabled"] or not cfg["api_key"] or not query:
            return json.dumps({"context": ""})

        banks = []
        if call_id:
            call = env["connect.call"].sudo().browse(int(call_id)).exists()
            if call:
                personal = call._hindsight_personal_bank()
                if personal:
                    banks.append(personal)
        if cfg["shared_bank"]:
            banks.append(cfg["shared_bank"])

        parts = []
        for bank in banks:
            try:
                text = hindsight_client.reflect(
                    cfg["base"], cfg["tenant"], cfg["api_key"], bank, query, timeout=8)
                if text:
                    parts.append(text)
            except Exception as e:
                logger.warning("Hindsight recall failed for bank %s: %s", bank, e)
        return json.dumps({"context": "\n\n".join(parts)})
