# Baseline: SQL profile of Twilio webhook processing (connect 2.0.9)

Measured 2026-08-28 on Oduflow env `connect-mirage` (odoo:19.0, template
twilio-staging, ~18k connect.call / ~96k connect.channel rows, modules
connect + connect_crm + connect_elevenlabs installed). Method: `odoo shell`,
counter wrapped around `Cursor.execute`, webhook sequences replayed via
`connect.call.on_call_status()` with Twilio client mocked, transaction rolled
back. Each step includes `env.flush_all()` at the end (savepoint overhead of
2 queries per step already subtracted). Timings are wall-clock in the shell,
first step of a run includes ORM warm-up.

## (a) Incoming direct call (5 webhooks)

| step                          | queries (debug_mode=False) | queries (debug_mode=True) |
|-------------------------------|---------------------------:|--------------------------:|
| parent ringing (call created) | 40                         | 62                        |
| child ringing                 | 41                         | 58                        |
| child in-progress             | 37                         | 51                        |
| child completed               | 35                         | 43                        |
| parent completed (finalize)   | 33                         | 41                        |
| **total**                     | **186**                    | **255**                   |

`debug_mode=True` (the staging/production default) adds ~37% queries: every
`debug()` call INSERTs a `connect.debug` row inside the webhook transaction.

## (b) Ring group, 5 legs (13 webhooks)

| step                        | queries |
|-----------------------------|--------:|
| parent ringing              | 36      |
| child0..4 ringing           | 40, 42, 42, 42, 42 |
| child0 in-progress          | 34      |
| child1..4 canceled          | 33 × 4  |
| child0 completed            | 35      |
| parent completed (finalize) | 34      |
| **total**                   | **471** |

Wall-clock 110–210 ms per webhook (idle DB, no concurrency).

## (c) Transfer

Variant 1 — Dial action webhook arrives AFTER the target leg's status
webhooks (target channel already exists): **the whole webhook transaction is
poisoned**. `_process_transfer_completion` → `_create_missing_transfer_channel`
INSERTs a channel with an existing SID → `UniqueViolation` → the `except`
swallows the Python exception but the transaction is already aborted →
every later SQL statement fails with `InFailedSqlTransaction` → HTTP 500,
the webhook status update is lost (no cron exists to repair it).

Variant 2 — Dial action arrives BEFORE any target-leg webhook:

| step                          | queries |
|-------------------------------|--------:|
| parent ringing                | 51      |
| child in-progress             | 47      |
| child completed               | 44      |
| dial action (creates channel) | 12      |
| parent completed (finalize)   | 35      |

## (d) Park + retrieve

| step                          | queries |
|-------------------------------|--------:|
| park_call                     | 8       |
| unpark_call (FOR UPDATE + Twilio redirect + write) | 13 |
| park_retrieve action          | 3       |

`unpark_call` holds a `SELECT ... FOR UPDATE` row lock on `connect_call`
across the synchronous Twilio REST call (mocked here; 100 ms – seconds live).

## Other baseline observations

- The per-call advisory lock (`pg_advisory_xact_lock(CALL_LOCK_CLASS,
  call.id)`) is taken only *after* `connect.channel.on_call_status()` has
  already INSERTed/UPDATEd `connect_channel` and possibly INSERTed
  `connect_call` — i.e. after row locks are held — and not at all when
  `channel.call` is unset.
- `connect.call` is written field-by-field in `on_call_status` (up to 8
  separate UPDATE/flush cycles per webhook) with `mail.thread` tracking
  active on every write after create.
- `debug()` in settings.py calls `inspect.stack()` (reads source files) on
  every invocation, even when nothing is logged.
