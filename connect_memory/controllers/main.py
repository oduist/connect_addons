import logging

from odoo import http, release
from odoo.http import request

_logger = logging.getLogger(__name__)
route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'

class MemoryController(http.Controller):
    """HTTP (JSON-RPC) contract between Odoo and the external memory service.

    The service PULLS pending events and request answers; Odoo never calls the
    service. All endpoints are token-protected (config parameter `connect_memory.token`,
    passed as `token` in the JSON-RPC params or in the `X-Memory-Token` header).

    Routes are `type="jsonrpc"`: send a body
        {"jsonrpc": "2.0", "method": "call", "params": {...}}
    and the return value comes back wrapped in `{"result": ...}`."""

    def _check_token(self, kw):
        expected = request.env["ir.config_parameter"].sudo().get_param(
            "connect_memory.token")
        token = kw.get("token") \
            or request.httprequest.headers.get("X-Memory-Token")
        return bool(expected) and token == expected

    # ------------------------------------------------------------------
    # outbox: service pulls events, then acks them
    # ------------------------------------------------------------------
    @http.route("/connect_memory/outbox/fetch", type=route_type, auth="public",
                methods=["POST"], csrf=False)
    def outbox_fetch(self, **kw):
        if not self._check_token(kw):
            return {"error": "unauthorized"}
        events = request.env["connect.memory.outbox"].sudo().fetch_batch(
            limit=int(kw.get("limit", 100)),
            domain=kw.get("domain"),
            engine=kw.get("engine"))
        return {"events": events}

    @http.route("/connect_memory/outbox/ack", type=route_type, auth="public",
                methods=["POST"], csrf=False)
    def outbox_ack(self, **kw):
        if not self._check_token(kw):
            return {"error": "unauthorized"}
        acked = request.env["connect.memory.outbox"].sudo().ack(
            kw.get("ids") or [],
            ok=kw.get("ok", True),
            error=kw.get("error"))
        return {"acked": acked}

    # ------------------------------------------------------------------
    # inbox: service claims requests, then writes answers back
    # ------------------------------------------------------------------
    @http.route("/connect_memory/inbox/fetch", type=route_type, auth="public",
                methods=["POST"], csrf=False)
    def inbox_fetch(self, **kw):
        if not self._check_token(kw):
            return {"error": "unauthorized"}
        requests = request.env["connect.memory.inbox"].sudo().claim_batch(
            limit=int(kw.get("limit", 20)),
            engine=kw.get("engine"))
        return {"requests": requests}

    @http.route("/connect_memory/inbox/answer", type=route_type, auth="public",
                methods=["POST"], csrf=False)
    def inbox_answer(self, **kw):
        if not self._check_token(kw):
            return {"error": "unauthorized"}
        if not kw.get("id"):
            return {"error": "missing id"}
        stored = request.env["connect.memory.inbox"].sudo().store_answer(
            kw.get("id"),
            kw.get("answer"),
            ok=kw.get("ok", True))
        return {"stored": bool(stored)}
