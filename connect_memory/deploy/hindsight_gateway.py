#!/usr/bin/env python3
"""Oduist Memory — Hindsight gateway service.

Pulls engine-neutral events from an Odoo `memory` module (table connect.memory.outbox),
loads them into Hindsight (retain), and answers connect.memory.inbox requests via
Hindsight reflect. Odoo never calls out — this service PULLS over HTTP.

Engine-specific projection (ADR-011): one neutral Odoo event ->
  retain item { content, document_id, context, timestamp }
into the per-customer bank `<BANK_PREFIX><commercial_partner_id>` (ADR-003).

Config via environment variables:
  ODOO_BASE_URL      e.g. https://litnimax-...velesagro.dev.oduist.com
  ODOO_TOKEN         must equal Odoo Connect setting `memory_service_token`
  HINDSIGHT_BASE     default https://api.hindsight.vectorize.io
  HINDSIGHT_KEY      Hindsight API key (hsk_...)
  HINDSIGHT_TENANT   default "default"
  BANK_PREFIX        default "partner-"
  POLL_INTERVAL      seconds between cycles, default 5
  BATCH              outbox batch size, default 50

Run a single cycle:   python hindsight_gateway.py --once
Run the poll loop:     python hindsight_gateway.py
"""
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

log = logging.getLogger("hindsight-gateway")


def load_dotenv():
    """Load a `.env` file next to this script into os.environ (no dependency).
    Existing environment variables win, so docker/CI/explicit exports override."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


class Config(object):
    def __init__(self):
        self.odoo_base = os.environ["ODOO_BASE_URL"].rstrip("/")
        self.odoo_token = os.environ["ODOO_TOKEN"]
        self.hs_base = os.environ.get(
            "HINDSIGHT_BASE", "https://api.hindsight.vectorize.io").rstrip("/")
        self.hs_key = os.environ["HINDSIGHT_KEY"]
        self.tenant = os.environ.get("HINDSIGHT_TENANT", "default")
        self.bank_prefix = os.environ.get("BANK_PREFIX", "partner-")
        self.poll_interval = float(os.environ.get("POLL_INTERVAL", "5"))
        self.batch = int(os.environ.get("BATCH", "50"))
        # Synchronous recall endpoint (Odoo -> gateway) for live voice calls.
        self.recall_port = int(os.environ.get("RECALL_PORT", "8790"))
        # Total reflect budget shared across the requested banks; keep it under
        # the caller's tool timeout (ElevenLabs recall tool ~10s).
        self.recall_budget = float(os.environ.get("RECALL_BUDGET", "8"))


# --------------------------------------------------------------------------
# Odoo side (JSON-RPC over the memory.* HTTP contract)
# --------------------------------------------------------------------------
def odoo_call(cfg, path, params):
    body = {"jsonrpc": "2.0", "method": "call", "params": params}
    resp = requests.post(cfg.odoo_base + path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError("Odoo RPC error: %s" % data["error"])
    result = data.get("result") or {}
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError("Odoo app error: %s" % result["error"])
    return result


# --------------------------------------------------------------------------
# Hindsight side
# --------------------------------------------------------------------------
def hs_headers(cfg):
    return {"Authorization": "Bearer %s" % cfg.hs_key,
            "Content-Type": "application/json"}


def bank_for(cfg, scope):
    cpid = (scope or {}).get("commercial_partner_id")
    return ("%s%s" % (cfg.bank_prefix, cpid)) if cpid else None


def hs_retain(cfg, bank, payload):
    item = {
        "content": payload.get("text") or "",
        "document_id": payload.get("dedup_key"),
        "context": "%s/%s" % (payload.get("domain"), payload.get("kind")),
    }
    if payload.get("occurred_at"):
        item["timestamp"] = payload["occurred_at"]
    if payload.get("tags"):
        item["tags"] = payload["tags"]
    url = "%s/v1/%s/banks/%s/memories" % (cfg.hs_base, cfg.tenant, bank)
    resp = requests.post(url, headers=hs_headers(cfg),
                         json={"items": [item], "async": False}, timeout=120)
    resp.raise_for_status()
    return resp.json()


def hs_reflect(cfg, bank, query, tags=None, timeout=120):
    body = {"query": query, "budget": "low", "max_tokens": 400}
    if tags:
        body["tags"] = tags
    url = "%s/v1/%s/banks/%s/reflect" % (cfg.hs_base, cfg.tenant, bank)
    resp = requests.post(url, headers=hs_headers(cfg), json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------
# Synchronous recall endpoint (Odoo -> gateway)
# --------------------------------------------------------------------------
# Live voice calls (connect_elevenlabs_memory) need an answer within the tool
# timeout, which the pull-based outbox/inbox loop cannot provide. Odoo POSTs the
# already-resolved banks + query here; the gateway reflects and returns merged
# context. The Hindsight key never leaves the service.
def handle_recall(cfg, body):
    """Reflect over the requested banks within one shared budget and merge.
    `body` = {"banks": [...], "query": str}. Returns {"context": str}."""
    banks = body.get("banks") or []
    query = body.get("query") or ""
    parts = []
    if query and banks:
        deadline = time.monotonic() + cfg.recall_budget
        for bank in banks:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                break
            try:
                data = hs_reflect(cfg, bank, query, timeout=remaining)
                text = ""
                if isinstance(data, dict):
                    text = (data.get("text") or data.get("answer")
                            or data.get("result") or "").strip()
                if text:
                    parts.append(text)
            except Exception as exc:
                log.warning("recall reflect failed for bank %s: %s", bank, exc)
    return {"context": "\n\n".join(parts)}


class _RecallHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") != "/recall":
            return self._reply(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw or b"{}")
        except Exception:
            return self._reply(400, {"error": "bad request"})
        expected = self.server.cfg.odoo_token
        if not expected or body.get("token") != expected:
            return self._reply(401, {"error": "unauthorized"})
        try:
            self._reply(200, handle_recall(self.server.cfg, body))
        except Exception as exc:
            log.warning("recall error: %s", exc)
            self._reply(500, {"error": str(exc)})

    def log_message(self, *args):  # keep the poll-loop logs clean
        pass

    def _reply(self, code, obj):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve_recall(cfg):
    httpd = ThreadingHTTPServer(("0.0.0.0", cfg.recall_port), _RecallHandler)
    httpd.cfg = cfg
    threading.Thread(target=httpd.serve_forever, name="recall-http",
                     daemon=True).start()
    log.info("recall endpoint listening on :%s", cfg.recall_port)
    return httpd


# --------------------------------------------------------------------------
# Cycles
# --------------------------------------------------------------------------
def process_outbox(cfg):
    res = odoo_call(cfg, "/connect_memory/outbox/fetch",
                    {"token": cfg.odoo_token, "limit": cfg.batch})
    events = res.get("events", [])
    ok_ids, failed = [], []
    for ev in events:
        payload = ev.get("payload") or {}
        try:
            bank = bank_for(cfg, payload.get("scope"))
            if not bank:
                raise ValueError("no commercial_partner_id in scope")
            hs_retain(cfg, bank, payload)
            ok_ids.append(ev["id"])
            log.info("retained event %s -> bank %s", ev["id"], bank)
        except Exception as exc:
            failed.append((ev.get("id"), str(exc)))
            log.warning("retain failed for event %s: %s", ev.get("id"), exc)
    if ok_ids:
        odoo_call(cfg, "/connect_memory/outbox/ack",
                  {"token": cfg.odoo_token, "ids": ok_ids, "ok": True})
    for fid, err in failed:
        odoo_call(cfg, "/connect_memory/outbox/ack",
                  {"token": cfg.odoo_token, "ids": [fid], "ok": False,
                   "error": err})
    return len(ok_ids), len(failed)


def process_inbox(cfg):
    res = odoo_call(cfg, "/connect_memory/inbox/fetch",
                    {"token": cfg.odoo_token, "limit": 10})
    requests_ = res.get("requests", [])
    done = 0
    for req in requests_:
        rid = req.get("id")
        body = req.get("request") or {}
        try:
            bank = bank_for(cfg, body.get("scope"))
            if not bank:
                raise ValueError("no commercial_partner_id in scope")
            ans = hs_reflect(cfg, bank, body.get("query") or "",
                             tags=body.get("tags"))
            odoo_call(cfg, "/connect_memory/inbox/answer",
                      {"token": cfg.odoo_token, "id": rid,
                       "answer": {"text": ans.get("text"),
                                  "usage": ans.get("usage")}, "ok": True})
            done += 1
            log.info("answered inbox %s -> bank %s", rid, bank)
        except Exception as exc:
            odoo_call(cfg, "/connect_memory/inbox/answer",
                      {"token": cfg.odoo_token, "id": rid,
                       "answer": {"error": str(exc)}, "ok": False})
            log.warning("reflect failed for inbox %s: %s", rid, exc)
    return done


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_dotenv()
    cfg = Config()
    once = "--once" in sys.argv
    log.info("gateway start | odoo=%s | hindsight=%s | bank_prefix=%s | once=%s",
             cfg.odoo_base, cfg.hs_base, cfg.bank_prefix, once)
    if not once:
        serve_recall(cfg)
    while True:
        try:
            retained, failed = process_outbox(cfg)
            answered = process_inbox(cfg)
            if retained or failed or answered:
                log.info("cycle done | retained=%s failed=%s answered=%s",
                         retained, failed, answered)
        except Exception as exc:
            log.error("cycle error: %s", exc)
        if once:
            break
        time.sleep(cfg.poll_interval)


if __name__ == "__main__":
    main()
