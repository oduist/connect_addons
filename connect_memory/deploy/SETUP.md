# Oduist Memory setup (Hindsight engine) — manual

A step-by-step "from zero to working" guide for the pair **Odoo `memory` + the Hindsight gateway**.
The current state of the `memory19` environment is already fully configured — see [section D](#d-current-state-of-the-memory19-environment-already-configured).
This guide is for reproducing it by hand on any other database/machine.

---

## 0. How it works (30 seconds)

Odoo **never calls** the memory engine. Everything works on a pull model:

```
message_post / write  ──►  connect.memory.outbox (pending)        ── Odoo only writes cheap rows
                              ▲
   the Hindsight gateway pulls ┘   POST /connect_memory/outbox/fetch  (+ /ack)
        │
        ▼  retain into the bank partner-<commercial_partner_id>
   Hindsight Cloud (https://api.hindsight.vectorize.io)

        │  reflect
        ▼
   POST /connect_memory/inbox/answer  ──►  connect.memory.inbox (done)   ── the answer is stored in Odoo
```

Three components:
1. **Odoo** with the `memory` module installed (correspondence capture → `connect.memory.outbox`).
2. **The gateway** `hindsight_gateway.py` (this directory) — a separate process that polls Odoo and loads events into Hindsight.
3. **Hindsight** — the external memory engine (key `hsk_...`).

Auth between the gateway and Odoo — the shared token (Connect settings `memory_service_token`).

---

## A. The Odoo side

### A.1. Install the `memory` module

In Oduflow:
```
pull_and_apply(env_name="memory19", install="memory")
```
or in the Odoo UI: **Apps** → find `memory` → Install.

Verify:
```python
# run_odoo_shell
mod = env['ir.module.module'].search([('name','=','memory')])
print(mod.state, mod.latest_version)   # installed  19.0.x.x
```

### A.2. Configure the parameters

**Connect → Settings → Memory → Settings** (requires *Connect / Administrator* rights). The **Memory** page:

| Field in the UI | connect.settings field | Value |
|---|---|---|
| **Enable memory capture** | `memory_enabled` | ✅ enable (the capture master switch) |
| **Memory service token** | `memory_service_token` | **any random string** — must **match** the gateway's `ODOO_TOKEN` |
| Default engine | `memory_default_engine` | `hindsight` |
| Outbox retention (days) | `memory_outbox_retention_days` | `7` (a daily cron cleans the `payload` of sent rows, leaving a thin tombstone for dedup; `0` = don't clean) |
| Memory service URL | `memory_service_url` | optional in the pull model (Odoo doesn't call out); can be left empty |

> The keys to Hindsight itself (`hsk_...`) are **not stored in Odoo** — they live only in the gateway (ADR-009).

The same way (without code):
```python
# run_odoo_shell
S = env['connect.settings']
S.set_param('memory_enabled', True)
S.set_param('memory_service_token', '<random_token>')
S.set_param('memory_default_engine', 'hindsight')
S.set_param('memory_outbox_retention_days', 7)
```

---

## B. The gateway side (this directory `memory/deploy/`)

### B.1. Fill in `.env`

```bash
cd memory/deploy
cp .env.example .env
```

```ini
# --- Odoo ---
ODOO_BASE_URL=http://localhost:50004      # the Odoo database URL
ODOO_TOKEN=<the same token as the Memory service token in Odoo>

# --- Hindsight ---
HINDSIGHT_BASE=https://api.hindsight.vectorize.io
HINDSIGHT_KEY=hsk_...                      # your Hindsight key
HINDSIGHT_TENANT=default

# --- Behavior ---
BANK_PREFIX=partner-                       # bank = partner-<commercial_partner_id>
POLL_INTERVAL=10                           # seconds between cycles
BATCH=50
```

Critical: **`ODOO_TOKEN` must match `memory_service_token`** in Odoo (Connect → Settings → Memory) — otherwise `/connect_memory/outbox/fetch` silently returns empty.

### B.2. Get the Hindsight key

The `hsk_...` key is issued in the Hindsight dashboard (vectorize.io). It lives **only** in the gateway's `.env` (in `.gitignore`, never committed).

### B.3. Start the gateway

Dependencies — just `requests`.

**Option 1 — locally (dev, as done now):**
```bash
python3 -m venv .venv && .venv/bin/pip install requests
.venv/bin/python hindsight_gateway.py          # poll loop
.venv/bin/python hindsight_gateway.py --once   # one cycle (for a check)
```
On this machine the project's shared venv is used:
```bash
/Users/poligon/Workspace/odoo19/.venv/bin/python hindsight_gateway.py
```

**Option 2 — Docker Compose (persistent, as in the README):**
```bash
docker compose up -d --build
docker compose logs -f
```
⚠️ On macOS/Docker Desktop `ODOO_BASE_URL=http://localhost:50004` **won't work** from inside the container
(`localhost` there is the container itself). Put a `docker-compose.override.yml` next to it (it's in `.gitignore`):
```yaml
services:
  memory-hindsight-gateway:
    environment:
      ODOO_BASE_URL: http://host.docker.internal:50004
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

**Option 3 — autostart on macOS (launchd), if you need a daemon that survives a reboot:**
create `~/Library/LaunchAgents/com.oduist.memory-hindsight.plist` with `ProgramArguments` =
`[/Users/poligon/Workspace/odoo19/.venv/bin/python, <absolute path>/hindsight_gateway.py]`,
`WorkingDirectory` = `memory/deploy`, and `launchctl load`.

---

## C. End-to-end check

1. **The gateway sees Odoo and Hindsight** — in the startup log:
   `gateway start | odoo=http://... | hindsight=https://api.hindsight.vectorize.io ...`

2. **Create a test event** ( Odoo shell ):
```python
import hashlib
text = "End-to-end setup connectivity check."
env['connect.memory.outbox'].enqueue({
    'event_id': 'evt-setup-test-0001',
    'dedup_key': 'setup-test-0001',
    'content_hash': 'sha256:' + hashlib.sha256(text.encode()).hexdigest(),
    'domain': 'partner', 'kind': 'message',
    'text': text, 'occurred_at': '2026-06-17T12:58:00Z', 'tags': ['setup-test'],
    'scope': {'commercial_partner_id': 2},
    'source': {'model': 'res.partner', 'res_id': 2},
})
env.cr.commit()
```

3. **After `POLL_INTERVAL` seconds** the `connect.memory.outbox` row should go `pending → sent`, and the gateway log should show `retained event ... -> bank partner-2`.

4. **The fact reached Hindsight** — the `fact_count` of the bank `partner-2` grew:
```bash
curl -s "https://api.hindsight.vectorize.io/v1/default/banks" \
  -H "Authorization: Bearer hsk_..."
```

Reflect check (inbox): create a `connect.memory.inbox` request (state=pending) with `request={'query':'...','scope':{'commercial_partner_id':2}}` — the gateway answers via Hindsight reflect and writes the `answer`.

---

## D. Current state of the `memory19` environment (already configured)

| Component | Value |
|---|---|
| Odoo | `http://localhost:50004` (container `oduflow-memory19-odoo`, live-mount of this repo) |
| Module `memory` | `installed`, version `19.0.1.2.0` |
| `memory_enabled` | `True` |
| `memory_service_token` | `f6d2b995c1abf3a_93f51ee5be19c778` (= `ODOO_TOKEN` in `.env`) |
| `memory_default_engine` | `hindsight` |
| `memory_outbox_retention_days` | `7` |
| Hindsight | `https://api.hindsight.vectorize.io`, tenant `default`, bank `partner-2` |
| Gateway | started locally: `/Users/poligon/Workspace/odoo19/.venv/bin/python hindsight_gateway.py` |

End-to-end verified: the created event `id=6` → `state=sent` (09:58:56 UTC),
`partner-2.fact_count` 7 → 9, `last_document_at` matched `sent_at`.

---

## E. If something doesn't work

| Symptom | Cause / fix |
|---|---|
| `outbox` piles up in `pending` | the gateway isn't running, or `ODOO_TOKEN ≠ memory_service_token` (fetch silently returns `[]`), or the gateway can't reach Odoo |
| Odoo auth errors in the gateway log | compare `ODOO_TOKEN` and `memory_service_token` character by character |
| `retain failed ... 401/403` | an invalid `HINDSIGHT_KEY` |
| `retain failed ... no commercial_partner_id in scope` | an event without `scope.commercial_partner_id` — the gateway doesn't know which bank to put it in |
| The gateway is running but the log is empty | stdout is block-buffered in a non-tty; run with `python -u` or via a terminal to see logs live |
| `outbox` is duplicated | auto-capture of `message_post` is enabled in `connect.memory.outbox` — that's normal; dedup by `(dedup_key, content_hash)` in `enqueue` + by `document_id` in Hindsight |
| GET `/v1/.../banks/<id>` → 405 | this endpoint doesn't support GET of a single bank; use GET `/v1/<tenant>/banks` (the list) |
| The Memory / Settings menus aren't visible | *Administration / Settings* rights are needed (`base.group_system`) |

Running a single cycle for quick diagnostics:
```bash
cd memory/deploy && /Users/poligon/Workspace/odoo19/.venv/bin/python hindsight_gateway.py --once
```
