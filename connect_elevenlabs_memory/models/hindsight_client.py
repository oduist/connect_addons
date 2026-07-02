# -*- coding: utf-8 -*-
"""Dependency-light Hindsight REST helpers.

Split into pure request/response shaping (unit-testable without network) and
thin `reflect`/`retain` callers. Mirrors the request shapes in
memory/deploy/hindsight_gateway.py."""
import requests

DEFAULT_BASE = "https://api.hindsight.vectorize.io"
DEFAULT_TENANT = "default"


def _headers(api_key):
    return {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}


def build_reflect_request(base, tenant, api_key, bank, query,
                          max_tokens=300, budget="low", tags=None):
    url = "%s/v1/%s/banks/%s/reflect" % (base.rstrip("/"), tenant, bank)
    body = {"query": query, "budget": budget, "max_tokens": max_tokens}
    if tags:
        body["tags"] = tags
    return url, _headers(api_key), body


def parse_reflect_response(data):
    """Return the synthesized answer text. The API has used `answer`/`text`/
    `result`; accept any, else empty string."""
    if not isinstance(data, dict):
        return ""
    return (data.get("answer") or data.get("text") or data.get("result") or "").strip()


def build_retain_request(base, tenant, api_key, bank, content,
                         document_id=None, context="voice/call",
                         timestamp=None, tags=None):
    url = "%s/v1/%s/banks/%s/memories" % (base.rstrip("/"), tenant, bank)
    item = {"content": content or "", "context": context}
    if document_id:
        item["document_id"] = document_id
    if timestamp:
        item["timestamp"] = timestamp
    if tags:
        item["tags"] = tags
    return url, _headers(api_key), {"items": [item], "async": False}


def reflect(base, tenant, api_key, bank, query, timeout=8, **kw):
    url, headers, body = build_reflect_request(base, tenant, api_key, bank, query, **kw)
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    return parse_reflect_response(resp.json())


def retain(base, tenant, api_key, bank, content, timeout=30, **kw):
    url, headers, body = build_retain_request(base, tenant, api_key, bank, content, **kw)
    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
