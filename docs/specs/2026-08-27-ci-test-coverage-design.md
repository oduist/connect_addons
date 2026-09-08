# CI that actually runs the tests — design

- **Ticket:** none yet
- **Modules:** repository-wide (`.github/workflows/addons.yml`)
- **Status:** draft, not approved
- **Date:** 2026-08-27

## Problem

The repository has 94 test methods across four modules. **CI runs none of them.**

`.github/workflows/addons.yml` ends with:

```
odoo --addons-path=$GITHUB_WORKSPACE --database=ephemeral ... --stop-after-init --no-http
  -i connect,connect_crm,connect_helpdesk,connect_elevenlabs,connect_book
```

There is no `--test-enable` and no `--test-tags`. The job installs five modules and
exits — a smoke check that the manifests load and the XML parses. Useful, but it is
not a test run, and the workflow's name ("CI") suggests otherwise.

Three separate gaps follow from that file:

| Gap | Detail |
| --- | --- |
| Tests never execute | No `--test-enable`. Every test in the repo runs only when a developer runs it by hand. |
| Half the modules are never installed | `connect_byoc`, `connect_website`, `connect_elevenlabs_knowledge`, `connect_elevenlabs_helpdesk` and `connect_elevenlabs_sale` are absent from `-i`. Nothing checks that they still install. |
| Feature branches are not covered | `on: push: branches: [18.0, 19.0]`. A branch is validated only after it is merged, which is the wrong end of the process. |

### Where the tests are today

| Module | Test methods | Installed in CI |
| --- | --- | --- |
| `connect` | 54 | yes |
| `connect_book` | 25 | yes |
| `connect_elevenlabs` | 11 | yes |
| `connect_elevenlabs_sale` | 4 | **no** |
| `connect_byoc` | 0 | **no** |
| `connect_crm` | 0 | yes |
| `connect_elevenlabs_helpdesk` | 0 | **no** |
| `connect_elevenlabs_knowledge` | 0 | **no** |
| `connect_helpdesk` | 0 | yes |
| `connect_website` | 0 | **no** |

Writing tests for the six empty modules is a separate effort and is out of scope here.
This design is about making the tests that *exist* run, and making every module's
install checked.

## Goals

1. Every test in the repository runs on CI, and a failure fails the build.
2. Every module in the repository is installed on CI.
3. A push to a feature branch is checked before the merge, not after.
4. The `connect_elevenlabs_sale` stock branch is exercised somewhere.

## Non-goals

- Writing the missing tests (separate tickets, one per module).
- Browser/tour tests. Nothing in the repo has them, and they need a different runner.
- Coverage measurement or a coverage gate.
- Anything about the 18.0 line beyond keeping it working as it does today.

## Decision 1 — enable tests in the existing job

Add `--test-enable` and switch the module list to all ten. One job, one database,
sequential install, tests run at the end of the load.

Rejected alternative: a second job dedicated to tests. It would double the
container start-up and the pip install for no isolation benefit — the install check
and the test run want the same database.

## Decision 2 — the `stock` question

`connect_elevenlabs_sale._items_in_stock` has two branches: `stock` installed (report
`qty_available`) and not installed (report `None`, so the agent says it does not track
the product). Both are supported configurations; `stock` is deliberately **not** in the
module's `depends`, because requiring it would force Inventory on every customer who
sells services.

The test file is symmetric — each configuration skips the other's assertions:

- without `stock`: `test_no_stock_module_reports_unknown` runs, three skip;
- with `stock`: those three run, the first skips.

So one database can never cover both branches. Three options:

| Option | Cost | Covers |
| --- | --- | --- |
| **A.** One job, no `stock` | none | the no-stock branch only |
| **B.** One job, with `stock` | +~40 s install | the stock branch only |
| **C.** Matrix of both | roughly doubles the job | both |

**Proposed: C**, as a `strategy.matrix` over a single `with_stock: [true, false]`
dimension, because the branch it covers is the one that talks to customers about
availability and the one that silently regressed before (`items_in_stock` used to be a
hardcoded `10`). If CI time turns out to matter more than that, fall back to **A** and
accept that the stock branch is only ever exercised by hand.

## Decision 3 — when the workflow runs

Extend the trigger to pull requests, keeping the pushes:

```yaml
on:
  push:
    branches: [18.0, 19.0]
  pull_request:
    branches: [18.0, 19.0]
```

Feature branches follow the `<series>.0-<feature>` convention and are merged through
pull requests, so `pull_request` covers them without CI running on every intermediate
push of every branch.

## Shape of the change

One file, `.github/workflows/addons.yml`:

- add the `pull_request` trigger;
- add a `with_stock` matrix dimension;
- install all ten modules, plus `stock` on the matrix leg that wants it;
- add `--test-enable`;
- keep `--stop-after-init`, and let the exit code fail the job.

## Open questions

1. Does the runner have enough memory for all ten modules plus Inventory on the
   `postgres:12` service currently pinned in the workflow?
2. `connect_website` bundles `twilio.min.js` and registers a website snippet — does it
   need `website` demo data to install cleanly on an empty database?
3. Should `18.0` get the same treatment in the same commit, or should 19.0 go first
   and 18.0 follow once it is proven?

## Definition of done

- A deliberately broken test fails the build. Verified by pushing one, not assumed.
- All ten modules appear in the install list and the job is green.
- Both matrix legs run, and the skip messages confirm each covered its own branch.
- The `TestS3Settings` and `TestAvailableSlots` suites pass on CI, not only locally.
