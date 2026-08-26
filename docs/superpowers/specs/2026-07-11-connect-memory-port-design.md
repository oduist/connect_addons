# Port `memory` / `memory_sale` → `connect_memory` / `connect_memory_sale`

Date: 2026-07-11
Status: approved

## Goal

Port two Odoo modules from the sibling repo `../memory_addons` into
`connect_addons`, with a **full** identifier rename and alignment to the
connect-suite conventions. The source repo is left untouched (copy, not move).

## Decisions (from brainstorming)

1. **Rename depth: full.** Rename the module *and* the model names, HTTP routes,
   and config-parameter keys (not just the module directory).
2. **Licensing: drop.** `memory` ships its own JWT-trial licensing, parallel to
   `connect`'s `oduist.license`. Remove it entirely; the suite is covered by
   `connect`'s licensing.
3. **`deploy/`: keep** (with updated routes). **`specs/`: drop.**
4. **Manifest metadata: align to connect** (`Other proprietary`, `1.0.0`,
   "Connect Memory" naming).
5. **Depends: `connect_memory` → `['mail']`** (provider-neutral base, no
   functional need for `connect`). `connect_memory_sale` →
   `['connect_memory', 'sale', 'account']`.
6. **Migration: fresh-install.** No ORM migration scripts. Deployed gateway +
   stored `memory.*` config/data must be re-pointed manually on the operator
   side.

## Rename map

Modules (directory + manifest technical name + external-id prefix):
- `memory` → `connect_memory`
- `memory_sale` → `connect_memory_sale`

Models (`_name` + DB table):
| Was | Now |
|---|---|
| `memory.outbox` | `connect.memory.outbox` |
| `memory.inbox` | `connect.memory.inbox` |
| `memory.mixin` | `connect.memory.mixin` |
| `memory.backfill` | `connect.memory.backfill` |
| `memory.backfill.wizard` | `connect.memory.backfill.wizard` |
| `memory.sale.mixin` | `connect.memory.sale.mixin` |

HTTP routes: `/memory/outbox/fetch|ack`, `/memory/inbox/fetch|answer`,
`/memory/health/<uid>` → `/connect_memory/...`

Config params: `memory.enabled`, `memory.service_url`, `memory.token`,
`memory.default_engine`, `memory.outbox_retention_days` → `connect_memory.*`

## Licensing removal

Delete: `models/memory_license.py`, `models/ir_module_module.py`, whole
`wizard/` (`memory.purchase_confirm` is the license payment-link wizard),
`data/memory_license_data.xml`, `views/memory_license_views.xml`,
`static/src/components/license_banner/*`.

Edit:
- `memory_mixin`: drop the `_memory_license_ok` gate; capture is governed only
  by the `connect_memory.enabled` master switch.
- `res_config_settings`: drop the `MEMORY_MODULES` registration import/append.
- `controllers/main.py`: rewrite the health endpoint without `memory.license`.
- both `__init__.py`: remove `post_init_hook` (it only started the trial clock);
  drop the `post_init_hook` key from both manifests.
- `security/ir.model.access.csv`: drop `memory.license` and
  `memory.purchase_confirm` rows.
- `views/memory_menus.xml`: drop license menu items.
- manifests: drop `external_dependencies` (PyJWT/cryptography) — no remaining
  JWT use; controllers compare the token as a plain string.

## Dependent module update: `connect_elevenlabs_memory`

Full rename breaks the already-present module; fix it in the same pass:
- `depends`: `"memory"` → `"connect_memory"`.
- code/tests: `env["memory.outbox"]` → `connect.memory.outbox`; params
  `memory.enabled|service_url|token` → `connect_memory.*`; route strings where
  they reference the base contract.

## `deploy/`

Copy to `connect_memory/deploy/` with routes `/memory/...` → `/connect_memory/...`
and param `memory.token` → `connect_memory.token` in `hindsight_gateway.py`,
`README.md`, `SETUP.md`, `.env.example`. Do **not** copy `.venv/`,
`__pycache__/`, or `.env` (secrets).

## Execution order

1. Copy both directories (excluding `__pycache__`, `specs/`, `.venv`, `.env`).
2. Rename by identifier class with a grep check after each class.
3. Remove the licensing layer.
4. Fix manifests + `__init__.py`.
5. Update `connect_elevenlabs_memory`.
6. Final grep sweep for stray `memory.` / `/memory/` outside expected strings;
   run `connect_memory_sale` / `connect_elevenlabs_memory` tests if a dev stack
   is available.
