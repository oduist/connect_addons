# -*- coding: utf-8 -*-
import json
import logging

import requests
from werkzeug.exceptions import Unauthorized

from odoo import http

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
        cfg = env["connect.settings"].sudo().get_recall_config()
        if not cfg["enabled"] or not cfg["service_url"] or not cfg["token"] or not query:
            return json.dumps({"context": ""})

        # Odoo owns caller -> partner, so it resolves the banks; the memory
        # service does the Hindsight reflect (it holds the engine key).
        banks = []
        if call_id:
            # call_id normally carries the connect.call id (dynamic var
            # sip_connect_call_ref, injected as the X-Connect-Call-Ref SIP header
            # by the agent). Also tolerate a raw Twilio CallSid by resolving the
            # owning channel. A miss just yields no personal bank instead of
            # erroring the call.
            channel = env["connect.channel"].sudo().search(
                [("sid", "=", call_id)], limit=1)
            if channel and channel.call:
                call = channel.call
            else:
                try:
                    call = env["connect.call"].sudo().browse(int(call_id)).exists()
                except (TypeError, ValueError):
                    call = env["connect.call"].browse()
            if call:
                personal = call._hindsight_personal_bank()
                if personal:
                    banks.append(personal)
        if not banks:
            return json.dumps({"context": ""})

        context = ""
        try:
            resp = requests.post(
                cfg["service_url"].rstrip("/") + "/recall",
                json={"token": cfg["token"], "banks": banks, "query": query},
                timeout=9)
            resp.raise_for_status()
            context = (resp.json() or {}).get("context") or ""
        except Exception as e:
            logger.warning("Memory recall failed: %s", e)
        return json.dumps({"context": context})
