# Runbook: Demo 5 — end to end (`pulse-demo-closeout`, task 3.1)

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints),
this closes the program's own closeout change. One synthetic patient crosses every seam PULSE
owns, in six stages, each asserting its outcome against the ledger before the next stage begins.
It runs two ways — offline against the local compose stack, and live against dev — with identical
assertions; only the transports differ.

Script: `scripts/demo/demo5_end_to_end.py`.

## What it shows

Six stages, in order, stopping at the first failed assertion:

1. **Identity resolution of a referral** — the cohort's three referral variants (mint, exact
   match, quarantine), resolved the same way `demo2_identity_matcher.py` resolves its own fixture
   cases.
2. **Consent ingress from an export landing row** — the fixture consent export row, swept twice;
   the first sweep declares, the second changes nothing.
3. **A signed board drag** — a legal drag commits, an illegal drag is rejected with the catalog's
   reason, and a tampered signature is refused before any rule runs.
4. **A verdict declared from the mart read** — the fixture mart row is relayed; the billing
   episode opens and qualifies, and an immediate rerun declares nothing new.
5. **Every window agrees with the ledger** — the board projection, the warehouse-landed events,
   and an independent fold of the journal are each reduced to `(subject_type, subject_key, state,
   as_of)` and compared to the ledger's own `current_state` row.
6. **The rebuild drill** — the enrollment scope's board row is captured, the columns the
   projection owns are deleted, `twenty_projection.rebuild` (task 2.3) repaints the scope, and the
   repainted row is asserted identical to the one captured before the drill, field for field.

A successful run ends with `=== Demo 5: all stages passed ===`, exit `0`, and a printed receipt —
one line per stage naming its assertion count and the subject keys it touched. A failed stage
prints `FAILED at stage '<name>': <what went wrong>` to stderr and the walk stops; no later stage
runs.

## Running it offline

Needs Docker (LocalStack + Postgres, `packages/ocean/infra/docker-compose.yml`) and this repo's
Python environment synced (`uv sync --all-packages`). No credential in the environment.

```bash
task demo:e2e
```

equivalent to:

```bash
uv run python scripts/demo/demo5_end_to_end.py
```

`--skip-compose-up` assumes the stack is already running; `--database-url` overrides the ledger
Postgres DSN (default: the compose stack's own `ledger-postgres`).

## Running it live

Live mode drives the same fixtures and the same assertions against the dev ledger, dev Twenty, and
`STG_EVENTS.EVENTS` — a `live_execution` task (WORKFLOW.md), run attended, never from a worktree.

```bash
task demo:e2e:live
```

equivalent to:

```bash
uv run python scripts/demo/demo5_end_to_end.py --live
```

Every credential is a name pinned in `scripts/demo/demo5_end_to_end.py`; every value comes from
the environment only, never a flag, never code. `resolve_live_config` reads them all before any
connection is attempted and refuses naming every variable still unset:

| Variable | What it's for |
|---|---|
| `DATABASE_URL` | The dev ledger's Postgres, for stage 4's `state_of_record` read and stage 5's fold/`current_state` windows — a plain `postgresql://` DSN (psycopg, not SQLAlchemy). |
| `PULSE_LEDGER_API_URL` | The dev ledger's command API and Twenty webhook route — the same variable `demo3_live_kanban_drag.py` reads for the same server. |
| `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET` | Signs stage 3's webhook deliveries — demo3's own secret. |
| `PULSE_TWENTY_DEV_URL` / `PULSE_TWENTY_DEV_TOKEN` | Dev Twenty, resolved by `pulse_core.twenty_deploy.resolve_target("dev")` — the same pair every credentialed Twenty target uses. |
| `CONSENT_INGRESS_CUSTOMERIO_TOKEN` | Stage 2's command-attribution credential (`customer.io`), the same variable `consent_ingress.cli` reads. |
| `VERDICT_RELAY_TOKEN` | Stage 4's command-attribution credential (`verdict-relay`), the same variable `verdict_relay.production` reads. |
| `PULSE_CORE_REPLAY_TOKEN` | Stage 6's replay credential — the kit's read-only facility (`pulse_core.replay`), the same one `twenty_projection.rebuild` uses in production. |
| `DEMO5_SNOWFLAKE_ACCOUNT` / `DEMO5_SNOWFLAKE_USER` / `DEMO5_SNOWFLAKE_WAREHOUSE` | This demo's own read-only reader for `STREAMLINE.STG_EVENTS.EVENTS` (stage 5's live warehouse window) — a different table and a different purpose than verdict-relay's mart credential. |
| `DEMO5_SNOWFLAKE_PASSWORD` **or** `DEMO5_SNOWFLAKE_PRIVATE_KEY_PATH` | Exactly one of the two — password or key-pair JWT, the same either/or `verdict_relay.production` enforces for its own Snowflake credential. |

The warehouse database, schema, and table (`STREAMLINE.STG_EVENTS.EVENTS`) are the published
contract's own coordinates (`docs/contracts/publishes.md` `snowflake-stg-events`), fixed in code,
never configuration.

Live mode assumes dev Twenty already carries a board record seeded for this demo's fixture
patient (`canonicalPatientId` = the consent export fixture's `subject_key`, `programCode` =
`"demo5"`) — the same "already-seeded card" precondition `demo3_live_kanban_drag.py` states for
its own drag.

## Reading the output

Every stage prints its own name before running and `ok: <n> assertion(s), subjects=[...]` after —
never a payload value, a credential value, or anything that could be protected health information
(all data is synthetic; a failure message names the stage, subject key, and field, never a
value). The final receipt is one JSON line per stage: `stage`, `assertion_count`,
`subject_keys`.

```bash
uv run python scripts/demo/demo5_end_to_end.py --help
```
