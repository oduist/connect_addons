# Results: Twilio webhook transaction optimization (connect 2.0.10)

Measured 2026-08-28 on the same env/method as the 2.0.9 baseline
(`webhook-tx-baseline-2.0.9.md`). Branch `regal-ape`, commits
`673d3ef..7f35c73`.

## SQL queries per webhook, before → after

### (a) Incoming direct call (debug_mode=False)

| step                          | 2.0.9 | 2.0.10 | Δ    |
|-------------------------------|------:|-------:|------|
| parent ringing (call created) | 40    | 23     | −43% |
| child ringing                 | 41    | 20     | −51% |
| child in-progress             | 37    | 11     | −70% |
| child completed               | 35    | 17     | −51% |
| parent completed (finalize)   | 33    | 12     | −64% |
| **call total**                | **186** | **83** | **−55%** |

With debug_mode=True (staging default): 255 → 152 (−40%).

### (b) Ring group, 5 legs — acceptance criterion ≥ −30%

| step                        | 2.0.9 | 2.0.10 | Δ    |
|-----------------------------|------:|-------:|------|
| parent ringing              | 36    | 17     | −53% |
| child ringing (×5)          | 40–42 | 19–21  | −50% |
| child0 in-progress          | 34    | 11     | −68% |
| child canceled (×4)         | 33    | 10     | −70% |
| child0 completed            | 35    | 14     | −60% |
| parent completed (finalize) | 34    | 13     | −62% |
| **call total (13 webhooks)**| **471** | **198** | **−58%** |

### (c) Transfer, dial action after the target's own webhooks

2.0.9: poisoned transaction (UniqueViolation in
`_create_missing_transfer_channel`) → InFailedSqlTransaction → HTTP 500,
webhook lost. 2.0.10: 8 queries, call finalizes.

### (d) Park + retrieve

| step                 | 2.0.9 | 2.0.10 |
|----------------------|------:|-------:|
| park_call            | 8     | 4      |
| unpark_call          | 13    | 5      |
| park_retrieve action | 3     | 3      |

No SELECT ... FOR UPDATE held across the Twilio redirect anymore: the slot
is claimed with one conditional UPDATE before the (timeout-bounded) REST
call, with compensation on failure.

Wall-clock per webhook in the shell dropped from 110–390 ms to 3–10 ms
(dominated by the removal of inspect.stack() in debug(), per-call
`search([])` in get_param, mail tracking and per-field flushes).

## Concurrent HTTP load (in-container, threaded server, db_maxconn=16)

Scenario per run: 20 identical webhooks (same CallSid/SequenceNumber)
fired in parallel + 4 ring-group calls × (parent + 10 legs fired
simultaneously, then the termination burst) = 112 requests, 12 client
threads.

- Runs C/D/E on final code: **112/112 HTTP 200, zero 5xx**, p50 ≈ 0.5 s,
  p99 ≈ 3 s (single-threaded green-let server, serialized per call).
- Duplicate-channel check: 0 duplicate SIDs; ring groups: exactly one
  connect.call per conversation (UNIQUE root_call_sid).
- Lock telemetry sampled at 50 ms during a 60-identical-webhook burst
  (finished in 1.64 s, 60/60 OK): max 2 advisory locks granted (root +
  per-call, one holder), max 11 transactions queued on the advisory lock,
  no non-advisory row-lock waiters — the queue is exactly the intended
  single-file serialization.
- Rollback/retry counter: lost visibility races and PostgreSQL
  serialization conflicts are replayed by odoo.service.model.retrying
  (≤5 tries); after the ConcurrencyError fix no request exhausted its
  retries.

## The REPEATABLE READ finding

Odoo cursors run at REPEATABLE READ and the snapshot is established by
framework queries before the controller body — so a webhook that queued
behind the advisory lock still cannot see what the previous holder
committed. The lock gives *ordering* (no deadlocks), not *visibility*.
Load-testing exposed this: lock-serialized losers re-searched, saw
nothing, re-INSERTed and failed. The final design therefore pairs the
lock with database-enforced uniqueness (UNIQUE(sid),
UNIQUE(root_call_sid)) and escalates snapshot-invisible races to
odoo.exceptions.ConcurrencyError, which the framework answers by
replaying the whole request on a fresh snapshot.
