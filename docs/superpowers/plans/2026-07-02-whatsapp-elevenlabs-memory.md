# WhatsApp → ElevenLabs → Hindsight Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `connect_elevenlabs_memory` module giving inbound-WhatsApp ElevenLabs agents long-term memory via Hindsight — live recall during the call and retain after it — scoped per commercial partner so it unifies with the `memory` module's `partner-<id>` banks.

**Architecture:** All pure Hindsight REST shaping (URL/body/parse) lives in a dependency-light `models/hindsight_client.py` so it is unit-testable without network. `connect.settings` gains Hindsight config. A token-protected controller endpoint (`/connect_elevenlabs/memory/recall`) resolves `call_id → connect.call → partner → bank` and returns synthesized context via Hindsight `reflect`. Retain happens by extending `connect.recording.create` (the post-call webhook already creates a recording carrying transcript + partner): enqueue to `memory.outbox` if `memory` is installed, else retain directly. A webhook agent-tool (`memory_recall`) and an extension helper wire it into the existing call flow.

**Tech Stack:** Odoo 19 (Python), `requests` (already a `connect` dep), ElevenLabs agent webhook tools, Hindsight REST (`/v1/{tenant}/banks/{bank}/{reflect,memories}`).

## Global Constraints

- Multi-version codebase: gate any version-specific API with `release.version_info[0]` (guard import **and** usage). In-repo pattern: `if release.version_info[0] >= 19: from odoo.models import Constraint`.
- Comments/docstrings in **English** only.
- License: `"Other proprietary"` (match sibling modules); author/maintainer `Oduist`.
- Module depends on `connect_elevenlabs`; do **not** add hard dependency on `memory` — detect it at runtime via `'memory.outbox' in self.env`.
- Bank naming: personal = `partner-<commercial_partner_id>` (prefix `partner-`, matches `memory/deploy/hindsight_gateway.py`), shared = configurable (`business-knowledge`), fallback = `whatsapp-<E164>`.
- Tool auth reuses header `x-elevenlabs-agent-token` vs setting `elevenlabs_agent_token`.
- Hindsight base `https://api.hindsight.vectorize.io`, tenant `default`, auth `Authorization: Bearer <key>`.
- Capture/memory failures must **never** break call handling — swallow + log.
- Commit messages: `[connect_elevenlabs_memory] <lowercase imperative subject>`.
- Tests run via oduflow `run_odoo_tests(env, "connect_elevenlabs_memory")` or CLI: `odoo -d <db> -u connect_elevenlabs_memory --test-enable --test-tags /connect_elevenlabs_memory --stop-after-init`. Python-only change → `restart=True`; field/model/data/manifest change → `upgrade`; brand-new module → `install`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `connect_elevenlabs_memory/__init__.py` | import `models`, `controllers` | Create |
| `connect_elevenlabs_memory/__manifest__.py` | manifest: depends `connect_elevenlabs`, data files | Create |
| `connect_elevenlabs_memory/models/__init__.py` | import model modules | Create |
| `connect_elevenlabs_memory/models/hindsight_client.py` | pure REST shaping + thin `reflect`/`retain` callers | Create |
| `connect_elevenlabs_memory/models/settings.py` | extend `connect.settings` with Hindsight config + `get_hindsight_config()` | Create |
| `connect_elevenlabs_memory/models/call.py` | `connect.call._hindsight_personal_bank()` | Create |
| `connect_elevenlabs_memory/models/recording.py` | extend `connect.recording.create` → retain | Create |
| `connect_elevenlabs_memory/models/whatsapp_sender.py` | `action_route_calls_to_agent(agent)` helper | Create |
| `connect_elevenlabs_memory/controllers/__init__.py` | import `main` | Create |
| `connect_elevenlabs_memory/controllers/main.py` | `POST /connect_elevenlabs/memory/recall` | Create |
| `connect_elevenlabs_memory/data/tools.xml` | `memory_recall` webhook tool + params | Create |
| `connect_elevenlabs_memory/views/settings.xml` | inherit ElevenLabs settings form, add "Memory" page | Create |
| `connect_elevenlabs_memory/security/ir.model.access.csv` | access for any new models (none new → minimal/empty) | Create |
| `connect_elevenlabs_memory/tests/__init__.py` | import tests | Create |
| `connect_elevenlabs_memory/tests/test_hindsight_client.py` | pure unit tests | Create |
| `connect_elevenlabs_memory/tests/test_settings.py` | config accessor test | Create |
| `connect_elevenlabs_memory/tests/test_bank.py` | bank-id resolution test | Create |
| `connect_elevenlabs_memory/tests/test_recall_controller.py` | recall endpoint test | Create |
| `connect_elevenlabs_memory/tests/test_retain.py` | retain-on-recording test | Create |
| `connect_elevenlabs_memory/tests/test_routing.py` | extension helper test | Create |

---

### Task 1: Module skeleton (installs cleanly)

**Files:**
- Create: `connect_elevenlabs_memory/__init__.py`
- Create: `connect_elevenlabs_memory/__manifest__.py`
- Create: `connect_elevenlabs_memory/models/__init__.py`
- Create: `connect_elevenlabs_memory/controllers/__init__.py`
- Create: `connect_elevenlabs_memory/security/ir.model.access.csv`

**Interfaces:**
- Produces: an installable module `connect_elevenlabs_memory` depending on `connect_elevenlabs`.

- [ ] **Step 1: Create `__init__.py`**

```python
# -*- coding: utf-8 -*-
from . import models
from . import controllers
```

- [ ] **Step 2: Create `models/__init__.py` (empty for now, filled by later tasks)**

```python
# -*- coding: utf-8 -*-
```

- [ ] **Step 3: Create `controllers/__init__.py` (empty for now)**

```python
# -*- coding: utf-8 -*-
```

- [ ] **Step 4: Create `__manifest__.py`**

```python
# -*- coding: utf-8 -*-
{
    "name": "Connect ElevenLabs Memory",
    "version": "1.0.0",
    "author": "Oduist",
    "maintainer": "Oduist",
    "support": "support@oduist.com",
    "license": "Other proprietary",
    "category": "Phone",
    "summary": "Long-term memory (Hindsight) for ElevenLabs voice agents",
    "description": "",
    "depends": ["connect_elevenlabs"],
    "external_dependencies": {"python": ["requests"]},
    "data": [],
    "installable": True,
}
```

Note: `data` is empty here on purpose — the referenced files do not exist yet. Later tasks append their own entry: Task 3 adds `"views/settings.xml"`, Task 6 adds `"data/tools.xml"`. Keeping `data` empty now lets the module install cleanly.

- [ ] **Step 5: Create empty `security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

(No new stored models are introduced; this file is a placeholder kept for future rules. Do not list it in the manifest `data` if empty.)

- [ ] **Step 6: Install the module**

Run (oduflow): `pull_and_apply(env, install="connect_elevenlabs_memory")`
Expected: install succeeds, no traceback.

- [ ] **Step 7: Commit**

```bash
git add connect_elevenlabs_memory/__init__.py connect_elevenlabs_memory/__manifest__.py connect_elevenlabs_memory/models/__init__.py connect_elevenlabs_memory/controllers/__init__.py connect_elevenlabs_memory/security/ir.model.access.csv
git commit -m "[connect_elevenlabs_memory] scaffold module depending on connect_elevenlabs"
```

---

### Task 2: Pure Hindsight REST client

**Files:**
- Create: `connect_elevenlabs_memory/models/hindsight_client.py`
- Modify: `connect_elevenlabs_memory/models/__init__.py`
- Create: `connect_elevenlabs_memory/tests/__init__.py`
- Test: `connect_elevenlabs_memory/tests/test_hindsight_client.py`

**Interfaces:**
- Produces:
  - `build_reflect_request(base, tenant, api_key, bank, query, max_tokens=300, budget="low", tags=None) -> (url, headers, body)`
  - `parse_reflect_response(data: dict) -> str`
  - `build_retain_request(base, tenant, api_key, bank, content, document_id=None, context="voice/call", timestamp=None, tags=None) -> (url, headers, body)`
  - `reflect(base, tenant, api_key, bank, query, timeout=8, **kw) -> str`
  - `retain(base, tenant, api_key, bank, content, timeout=30, **kw) -> dict`

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import test_hindsight_client
```

`connect_elevenlabs_memory/tests/test_hindsight_client.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (no `hindsight_client`).

- [ ] **Step 3: Write the implementation**

`connect_elevenlabs_memory/models/hindsight_client.py`:
```python
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
```

`connect_elevenlabs_memory/models/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import hindsight_client
```

- [ ] **Step 4: Run test to verify it passes**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add connect_elevenlabs_memory/models/hindsight_client.py connect_elevenlabs_memory/models/__init__.py connect_elevenlabs_memory/tests/__init__.py connect_elevenlabs_memory/tests/test_hindsight_client.py
git commit -m "[connect_elevenlabs_memory] add pure hindsight rest client with unit tests"
```

---

### Task 3: Settings config + view

**Files:**
- Create: `connect_elevenlabs_memory/models/settings.py`
- Create: `connect_elevenlabs_memory/views/settings.xml`
- Modify: `connect_elevenlabs_memory/models/__init__.py`
- Modify: `connect_elevenlabs_memory/__manifest__.py` (restore `views/settings.xml` in `data`)
- Test: `connect_elevenlabs_memory/tests/test_settings.py`

**Interfaces:**
- Consumes: `connect.settings.get_param(name)` (returns the field value via `getattr`).
- Produces: `connect.settings.get_hindsight_config() -> {"enabled": bool, "base": str, "tenant": str, "api_key": str, "shared_bank": str}`.

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/test_settings.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHindsightSettings(TransactionCase):
    def test_get_hindsight_config_defaults_and_overrides(self):
        settings = self.env["connect.settings"]
        settings.set_param("hindsight_api_key", "hsk_secret")
        settings.set_param("hindsight_memory_enabled", True)
        cfg = settings.get_hindsight_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["api_key"], "hsk_secret")
        self.assertEqual(cfg["base"], "https://api.hindsight.vectorize.io")
        self.assertEqual(cfg["tenant"], "default")
        self.assertEqual(cfg["shared_bank"], "business-knowledge")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — `AttributeError: get_hindsight_config`.

- [ ] **Step 3: Write the model**

`connect_elevenlabs_memory/models/settings.py`:
```python
# -*- coding: utf-8 -*-
from odoo import models, fields


class ConnectSettings(models.Model):
    _inherit = "connect.settings"

    hindsight_memory_enabled = fields.Boolean(string="Hindsight Memory Enabled")
    hindsight_base_url = fields.Char(
        string="Hindsight Base URL", default="https://api.hindsight.vectorize.io")
    hindsight_tenant = fields.Char(string="Hindsight Tenant", default="default")
    hindsight_api_key = fields.Char(
        string="Hindsight API Key", groups="base.group_erp_manager")
    display_hindsight_api_key = fields.Char()
    hindsight_shared_bank = fields.Char(
        string="Shared Knowledge Bank", default="business-knowledge")

    def get_hindsight_config(self):
        get = self.sudo().get_param
        return {
            "enabled": bool(get("hindsight_memory_enabled")),
            "base": get("hindsight_base_url") or "https://api.hindsight.vectorize.io",
            "tenant": get("hindsight_tenant") or "default",
            "api_key": get("hindsight_api_key") or "",
            "shared_bank": get("hindsight_shared_bank") or "business-knowledge",
        }
```

`connect_elevenlabs_memory/models/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import hindsight_client
from . import settings
```

- [ ] **Step 4: Create the settings view (adds a "Memory" page to the ElevenLabs settings form)**

`connect_elevenlabs_memory/views/settings.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="connect_elevenlabs_memory_settings_form" model="ir.ui.view">
    <field name="name">connect_elevenlabs_memory_settings_form</field>
    <field name="model">connect.settings</field>
    <field name="inherit_id" ref="connect_elevenlabs.connect_elevenlabs_settings_form"/>
    <field name="arch" type="xml">
      <xpath expr="//notebook" position="inside">
        <page name="memory" string="Memory">
          <group>
            <group>
              <field name="hindsight_memory_enabled"/>
              <field name="hindsight_base_url"/>
              <field name="hindsight_tenant"/>
              <field name="display_hindsight_api_key" password="1" string="Hindsight API Key"/>
              <field name="hindsight_shared_bank"/>
            </group>
          </group>
        </page>
      </xpath>
    </field>
  </record>
</odoo>
```

Note: confirm the ElevenLabs settings form contains a `<notebook>`; from `connect_elevenlabs/views/settings.xml` it uses `<page>` elements, so a `<notebook>` parent exists. If the external id differs, use the actual id of the form record (`connect_elevenlabs.connect_elevenlabs_settings_form`).

- [ ] **Step 5: Restore data entry in manifest**

In `__manifest__.py`, ensure `"data"` contains `"views/settings.xml"` (and later `"data/tools.xml"`).

- [ ] **Step 6: Run test to verify it passes**

Run (oduflow, field+view change): `pull_and_apply(env, upgrade="connect_elevenlabs_memory")` then `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add connect_elevenlabs_memory/models/settings.py connect_elevenlabs_memory/views/settings.xml connect_elevenlabs_memory/models/__init__.py connect_elevenlabs_memory/__manifest__.py connect_elevenlabs_memory/tests/test_settings.py
git commit -m "[connect_elevenlabs_memory] add hindsight settings config and view"
```

---

### Task 4: Per-caller bank resolution

**Files:**
- Create: `connect_elevenlabs_memory/models/call.py`
- Modify: `connect_elevenlabs_memory/models/__init__.py`
- Test: `connect_elevenlabs_memory/tests/test_bank.py`

**Interfaces:**
- Consumes: `connect.call.partner` (Many2one res.partner), `connect.call.caller` (Char, E.164).
- Produces: `connect.call._hindsight_personal_bank() -> str | False` returning `partner-<commercial_id>`, else `whatsapp-<caller>`, else `False`.

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/test_bank.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPersonalBank(TransactionCase):
    def test_bank_from_partner_uses_commercial(self):
        company = self.env["res.partner"].create({"name": "Acme", "is_company": True})
        contact = self.env["res.partner"].create({"name": "Bob", "parent_id": company.id})
        call = self.env["connect.call"].create({"partner": contact.id, "caller": "+15551230000"})
        self.assertEqual(call._hindsight_personal_bank(), "partner-%s" % company.id)

    def test_bank_fallback_to_caller_number(self):
        call = self.env["connect.call"].create({"caller": "+15559990000"})
        self.assertEqual(call._hindsight_personal_bank(), "whatsapp-+15559990000")

    def test_bank_false_when_no_partner_no_caller(self):
        call = self.env["connect.call"].create({"caller": False})
        self.assertFalse(call._hindsight_personal_bank())
```

Note: if `connect.call.create` requires more mandatory fields in this codebase, add the minimal ones the model demands (inspect `connect/models/call.py`); the assertions above are the invariant.

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — `AttributeError: _hindsight_personal_bank`.

- [ ] **Step 3: Write the model**

`connect_elevenlabs_memory/models/call.py`:
```python
# -*- coding: utf-8 -*-
from odoo import models


class ConnectCall(models.Model):
    _inherit = "connect.call"

    def _hindsight_personal_bank(self):
        """Bank id for this caller's personal memory:
        partner-<commercial_partner_id> when a partner is known (unifies with
        the `memory` module), else whatsapp-<E164>, else False."""
        self.ensure_one()
        partner = self.partner
        if partner:
            commercial = partner.commercial_partner_id or partner
            return "partner-%s" % commercial.id
        num = (self.caller or "").strip()
        return ("whatsapp-%s" % num) if num else False
```

`connect_elevenlabs_memory/models/__init__.py`: append `from . import call`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pull_and_apply(env, upgrade="connect_elevenlabs_memory")` then `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add connect_elevenlabs_memory/models/call.py connect_elevenlabs_memory/models/__init__.py connect_elevenlabs_memory/tests/test_bank.py
git commit -m "[connect_elevenlabs_memory] add per-caller hindsight bank resolution"
```

---

### Task 5: Recall controller endpoint

**Files:**
- Create: `connect_elevenlabs_memory/controllers/main.py`
- Modify: `connect_elevenlabs_memory/controllers/__init__.py`
- Test: `connect_elevenlabs_memory/tests/test_recall_controller.py`

**Interfaces:**
- Consumes: `connect.settings.get_hindsight_config()`, `connect.call._hindsight_personal_bank()`, `hindsight_client.reflect(...)`.
- Produces: HTTP route `POST /connect_elevenlabs/memory/recall` → JSON `{"context": str}`; header auth `x-elevenlabs-agent-token` vs `elevenlabs_agent_token`.

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/test_recall_controller.py`:
```python
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
        self.env.cr.commit()
        self.addCleanup(self.call.unlink)

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
```

Note: `HttpCase` + `url_open` needs committed data; `self.env.cr.commit()` is used deliberately here (test tears the records down in `addCleanup`).

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Write the controller**

`connect_elevenlabs_memory/controllers/main.py`:
```python
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
```

`connect_elevenlabs_memory/controllers/__init__.py`:
```python
# -*- coding: utf-8 -*-
from . import main
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pull_and_apply(env, restart=True)` (Python-only) then `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS (both cases).

- [ ] **Step 5: Commit**

```bash
git add connect_elevenlabs_memory/controllers/main.py connect_elevenlabs_memory/controllers/__init__.py connect_elevenlabs_memory/tests/test_recall_controller.py
git commit -m "[connect_elevenlabs_memory] add token-protected memory recall endpoint"
```

---

### Task 6: `memory_recall` agent tool (data)

**Files:**
- Create: `connect_elevenlabs_memory/data/tools.xml`
- Modify: `connect_elevenlabs_memory/__manifest__.py` (add `data/tools.xml`)
- Test: `connect_elevenlabs_memory/tests/test_tool_data.py`

**Interfaces:**
- Consumes: `connect.elevenlabs_agent_tool` (`tool_type=webhook`, `path`, `param_type=body`), `connect.agent_tool_params` (`value_type ∈ {description, dynamic_variable}`).
- Produces: XML record `agent_tool_memory_recall` with two params (`query`, `call_id`).

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/test_tool_data.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — `ValueError` (external id not found).

- [ ] **Step 3: Create the data file**

`connect_elevenlabs_memory/data/tools.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <data noupdate="1">
    <record id="agent_tool_memory_recall" model="connect.elevenlabs_agent_tool">
      <field name="name">memory_recall</field>
      <field name="description">Recall long-term memory about the caller and the business.
Call this at the start of the conversation and whenever prior context would help
(the caller's history, preferences, past requests, or business facts/FAQ).
Pass a natural-language `query` describing what you want to remember.
The returned `context` is trusted background — never read it aloud verbatim or
mention that a tool was used.</field>
      <field name="tool_type">webhook</field>
      <field name="path">/connect_elevenlabs/memory/recall</field>
      <field name="method">POST</field>
      <field name="param_type">body</field>
      <field name="response_timeout_secs">10</field>
    </record>

    <record id="memory_recall_param_query" model="connect.agent_tool_params">
      <field name="name">query</field>
      <field name="data_type">string</field>
      <field name="required">True</field>
      <field name="value_type">description</field>
      <field name="description">What to recall, in natural language (e.g. "caller identity and recent requests").</field>
      <field name="tool" ref="agent_tool_memory_recall"/>
    </record>

    <record id="memory_recall_param_call_id" model="connect.agent_tool_params">
      <field name="name">call_id</field>
      <field name="data_type">integer</field>
      <field name="required">True</field>
      <field name="value_type">dynamic_variable</field>
      <field name="dynamic_variable">call_id</field>
      <field name="tool" ref="agent_tool_memory_recall"/>
    </record>
  </data>
</odoo>
```

Note: the `connect.elevenlabs_agent_tool.create` hook only syncs non-system tools to ElevenLabs when `not self.env.context.get('install_mode')`. Odoo sets `install_mode=True` while loading data files, so this record will **not** trigger a network sync at install (same as the existing `transfer_to_exten`/calendar tools). Syncing to ElevenLabs happens later when an admin attaches the tool to an agent and that agent is synced.

- [ ] **Step 4: Add to manifest**

In `__manifest__.py` `data`, add `"data/tools.xml"` after `"views/settings.xml"`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pull_and_apply(env, upgrade="connect_elevenlabs_memory")` then `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add connect_elevenlabs_memory/data/tools.xml connect_elevenlabs_memory/__manifest__.py connect_elevenlabs_memory/tests/test_tool_data.py
git commit -m "[connect_elevenlabs_memory] add memory_recall webhook agent tool"
```

---

### Task 7: Retain conversation on post-call

**Files:**
- Create: `connect_elevenlabs_memory/models/recording.py`
- Modify: `connect_elevenlabs_memory/models/__init__.py`
- Test: `connect_elevenlabs_memory/tests/test_retain.py`

**Interfaces:**
- Consumes: `connect.recording` fields `partner`, `elevenlabs_transcript`, `elevenlabs_summary`, `call`; `connect.settings.get_hindsight_config()`; `hindsight_client.retain(...)`; optional `memory.outbox.enqueue(envelope)` + `memory.outbox._memory_content_hash(text)`.
- Produces: side-effect — on recording create with partner + transcript and memory enabled, a retain is issued (via `memory.outbox` if installed, else direct Hindsight).

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/test_retain.py`:
```python
# -*- coding: utf-8 -*-
from unittest.mock import patch
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRetain(TransactionCase):
    def _enable(self):
        s = self.env["connect.settings"]
        s.set_param("hindsight_memory_enabled", True)
        s.set_param("hindsight_api_key", "hsk_x")

    def test_direct_retain_when_memory_absent(self):
        self._enable()
        company = self.env["res.partner"].create({"name": "Acme", "is_company": True})
        with patch("odoo.addons.connect_elevenlabs_memory.models.recording."
                   "ConnectRecording._memory_module_present", return_value=False), \
             patch("odoo.addons.connect_elevenlabs_memory.models.recording."
                   "hindsight_client.retain") as retain:
            self.env["connect.recording"].create({
                "partner": company.id,
                "elevenlabs_summary": "Booked a demo.",
                "elevenlabs_transcript": "agent: hi\nuser: book a demo",
            })
            self.assertTrue(retain.called)
            # retain(base, tenant, api_key, bank, content, ...) — bank is arg index 3
            self.assertEqual(retain.call_args[0][3], "partner-%s" % company.id)

    def test_no_retain_when_disabled(self):
        company = self.env["res.partner"].create({"name": "Acme2", "is_company": True})
        with patch("odoo.addons.connect_elevenlabs_memory.models.recording."
                   "hindsight_client.retain") as retain:
            self.env["connect.recording"].create({
                "partner": company.id,
                "elevenlabs_summary": "x",
            })
            self.assertFalse(retain.called)
```

Note: adjust the `retain` bank assertion to match the call convention chosen in Step 3 (this plan calls `hindsight_client.retain(base, tenant, api_key, bank, content, document_id=...)` positionally — bank is the 4th positional arg).

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — retain not called (override missing).

- [ ] **Step 3: Write the model**

`connect_elevenlabs_memory/models/recording.py`:
```python
# -*- coding: utf-8 -*-
import logging

from odoo import api, models

from . import hindsight_client

logger = logging.getLogger(__name__)


class ConnectRecording(models.Model):
    _inherit = "connect.recording"

    def _memory_module_present(self):
        return "memory.outbox" in self.env

    def _hindsight_retain_text(self):
        self.ensure_one()
        summary = self.elevenlabs_summary or ""
        transcript = self.elevenlabs_transcript or ""
        return ("%s\n\n%s" % (summary, transcript)).strip()

    def _retain_to_hindsight(self):
        """Push this recording's transcript into the caller's partner bank.
        Never raises into call handling."""
        for rec in self:
            try:
                cfg = self.env["connect.settings"].sudo().get_hindsight_config()
                if not cfg["enabled"] or not cfg["api_key"]:
                    continue
                partner = rec.partner
                if not partner:
                    continue
                text = rec._hindsight_retain_text()
                if not text:
                    continue
                commercial = partner.commercial_partner_id or partner
                bank = "partner-%s" % commercial.id
                dedup = "connect-recording-%s" % rec.id
                if rec._memory_module_present():
                    outbox = self.env["memory.outbox"].sudo()
                    envelope = {
                        "domain": "voice",
                        "kind": "call",
                        "dedup_key": dedup,
                        "text": text,
                        "content_hash": outbox._memory_content_hash(text),
                        "scope": {
                            "commercial_partner_id": commercial.id,
                            "commercial_partner_name": commercial.display_name,
                        },
                        "source": {
                            "model": "connect.recording",
                            "res_id": rec.id,
                            "company_id": self.env.company.id,
                        },
                    }
                    outbox.enqueue(envelope)
                else:
                    hindsight_client.retain(
                        cfg["base"], cfg["tenant"], cfg["api_key"], bank, text,
                        document_id=dedup, context="voice/call")
            except Exception as e:
                logger.warning("Hindsight retain failed for recording %s: %s", rec.id, e)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._retain_to_hindsight()
        return records
```

`connect_elevenlabs_memory/models/__init__.py`: append `from . import recording`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pull_and_apply(env, upgrade="connect_elevenlabs_memory")` then `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add connect_elevenlabs_memory/models/recording.py connect_elevenlabs_memory/models/__init__.py connect_elevenlabs_memory/tests/test_retain.py
git commit -m "[connect_elevenlabs_memory] retain post-call transcript into partner bank"
```

---

### Task 8: WhatsApp → agent routing helper

**Files:**
- Create: `connect_elevenlabs_memory/models/whatsapp_sender.py`
- Modify: `connect_elevenlabs_memory/models/__init__.py`
- Test: `connect_elevenlabs_memory/tests/test_routing.py`

**Interfaces:**
- Consumes: `connect.whatsapp_sender.number` (E.164), `connect.exten` (`number`, `dst`), `connect.elevenlabs_agent`.
- Produces: `connect.whatsapp_sender.action_route_calls_to_agent(agent) -> connect.exten` — idempotently creates/updates an extension `number = sender.number` with `dst = agent`.

- [ ] **Step 1: Write the failing test**

`connect_elevenlabs_memory/tests/test_routing.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRouting(TransactionCase):
    def test_creates_extension_for_number_pointing_at_agent(self):
        sender = self.env["connect.whatsapp_sender"].create({"number": "+15557778888"})
        agent = self.env["connect.elevenlabs_agent"].search([], limit=1)
        if not agent:
            self.skipTest("no ElevenLabs agent available in this env")
        exten = sender.action_route_calls_to_agent(agent)
        self.assertEqual(exten.number, "+15557778888")
        self.assertEqual(exten.model, "connect.elevenlabs_agent")
        self.assertEqual(exten.res_id, agent.id)
```

Note: creating a `connect.elevenlabs_agent` requires ElevenLabs API side effects, so the test uses an existing agent or skips. If `connect.whatsapp_sender.create` needs more fields, add the minimal required ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: FAIL — `AttributeError: action_route_calls_to_agent`.

- [ ] **Step 3: Write the model**

`connect_elevenlabs_memory/models/whatsapp_sender.py`:
```python
# -*- coding: utf-8 -*-
from odoo import models


class ConnectWhatsappSender(models.Model):
    _inherit = "connect.whatsapp_sender"

    def action_route_calls_to_agent(self, agent):
        """Route inbound WhatsApp calls on this sender's number to an ElevenLabs
        agent by creating/updating a matching connect.exten. `route_call` looks
        up the extension by the dialed WhatsApp number, so number must equal the
        sender number in E.164."""
        self.ensure_one()
        Exten = self.env["connect.exten"]
        exten = Exten.search([("number", "=", self.number)], limit=1)
        vals = {"number": self.number, "model": "connect.elevenlabs_agent",
                "res_id": agent.id}
        if exten:
            exten.write(vals)
        else:
            exten = Exten.create(vals)
        return exten
```

`connect_elevenlabs_memory/models/__init__.py`: append `from . import whatsapp_sender`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pull_and_apply(env, upgrade="connect_elevenlabs_memory")` then `run_odoo_tests(env, "connect_elevenlabs_memory")`
Expected: PASS (or SKIP if no agent in env).

- [ ] **Step 5: Commit**

```bash
git add connect_elevenlabs_memory/models/whatsapp_sender.py connect_elevenlabs_memory/models/__init__.py connect_elevenlabs_memory/tests/test_routing.py
git commit -m "[connect_elevenlabs_memory] add whatsapp->agent extension routing helper"
```

---

## Manual verification (after Task 8, on an oduflow env)

- [ ] In ElevenLabs settings (Memory page): enable memory, set Hindsight API key (same value as `memory/deploy/.env`), keep base/tenant defaults, shared bank `business-knowledge`.
- [ ] Seed the `business-knowledge` bank with a couple of facts (via Hindsight MCP `retain` or the gateway).
- [ ] Attach the `memory_recall` tool to the target ElevenLabs agent and sync the agent (pushes the tool to ElevenLabs).
- [ ] Route the WhatsApp number to the agent: `sender.action_route_calls_to_agent(agent)` (or create the extension in the UI).
- [ ] Confirm WhatsApp Business Calling is enabled for the sender in Twilio/WhatsApp Manager (external; note region limits: not US/Canada/Egypt/Vietnam/Nigeria).
- [ ] Place a real WhatsApp call → agent answers → ask something the `business-knowledge` bank knows → verify the agent uses it.
- [ ] Hang up → confirm a memory appears in `partner-<id>` (Hindsight `list_memories`, or the `memory.outbox` row → gateway retains it).

## External prerequisites (not code)

- WhatsApp Business Calling enabled on the Meta/Twilio side (messaging tier ≥ 2000/24h; Calling enabled in WhatsApp Manager).
- `elevenlabs_agent_token` configured (already required by `connect_elevenlabs`).
- Hindsight API key available (reuse the `memory/deploy/.env` value).
