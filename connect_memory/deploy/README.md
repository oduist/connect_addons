# Oduist Memory — Hindsight gateway (deploy)

External per-engine service for **Oduist Memory** (engine: Hindsight). It PULLS
engine-neutral events from the Odoo `memory` module and projects them into
Hindsight (see `../specs/`):

- `connect.memory.outbox` events → Hindsight **retain** into bank `partner-<commercial_partner_id>`
- `connect.memory.inbox` requests → Hindsight **reflect** → answer written back to Odoo

It also **serves** one synchronous endpoint — `POST /recall` — for live voice
calls (`connect_elevenlabs_memory`) that cannot wait for the pull-based inbox
loop. That is the one place Odoo calls the service instead of the service
pulling; the Hindsight key still never leaves here.

This is a separate product component bundled here for convenience; it does NOT
run inside Odoo (the `deploy/` folder is ignored by the Odoo module loader).
Secrets are passed via environment variables and are never committed.

## Files
- `hindsight_gateway.py` — the service (stdlib + `requests`)
- `requirements.txt` — `requests`
- `Dockerfile` — slim Python image
- `docker-compose.yml` — example runner (expose `RECALL_PORT` so Odoo can reach `/recall`)
- `.env.example` — config template (copy to `.env`)

## Run with Docker Compose
```bash
cp .env.example .env          # fill ODOO_TOKEN + HINDSIGHT_KEY etc.
docker compose up -d --build
docker compose logs -f
```

`ODOO_TOKEN` must match the Odoo config parameter `connect_memory.token`
(Settings → Memory), and `connect_memory.enabled` must be on for capture.

## Run locally (no Docker)
```bash
pip install -r requirements.txt
export ODOO_BASE_URL="https://..."   ODOO_TOKEN="..."
export HINDSIGHT_KEY="hsk_..."       HINDSIGHT_BASE="https://api.hindsight.vectorize.io"
python hindsight_gateway.py --once   # one cycle (testing)
python hindsight_gateway.py          # poll loop
```

## Odoo contract (JSON-RPC, token-protected)
- `POST /connect_memory/outbox/fetch` → `{events:[{id, payload}]}`
- `POST /connect_memory/outbox/ack`   `{ids, ok, error}`
- `POST /connect_memory/inbox/fetch`  → `{requests:[{id, request}]}`
- `POST /connect_memory/inbox/answer` `{id, answer, ok}`

Token in JSON-RPC `params.token` or header `X-Memory-Token`.

## Recall endpoint (gateway serves this; Odoo → gateway)
- `POST /recall` `{token, banks:[...], query}` → `{context}` — reflects each bank
  within one shared budget (`RECALL_BUDGET`, default 8s) and merges the answers.
- Auth: body `token` must equal `ODOO_TOKEN` (= Odoo `connect_memory.token`).
- Listens on `RECALL_PORT` (default `8790`). Set the Odoo `connect_memory.service_url`
  to this `host:port` (must be reachable from the Odoo container).
