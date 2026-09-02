# Runbook: Demo 4 — live declare-back on dev (`billing-state`, task 4.1)

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints),
this closes Phase 4's `billing-state` change. Like Demo 3 this one is **live** — it needs a
reachable dev Snowflake mart and a dev Postgres holding the migrated ledger schema, so `task check`
holds only the offline gates; a human runs the script attended (WORKFLOW.md `live_execution`),
and its output — subject keys, states, counts, wall-clock timings — is the receipt.

Script: `scripts/demo/demo4_billing_declare_back.py`.

## What it shows

The script seeds its own controlled scenario for every check rather than relying on ambient mart
data. Four checks, in order:

1. A synthetic `billing_episode` is opened at `open` and a positive `billing_eligibility` mart row
   is declared for it. After `run_relay`, `state_of_record` for the episode is `qualified`, and
   the batch's `transitioned == 1`.
2. A positive `coverage_eligibility` mart row is declared for a fresh, never-opened `(patient,
   payer)` pair. After `run_relay`, `state_of_record` for the coverage subject is
   `verified_active` with no separate genesis event — mint-on-first-declare.
3. An immediate second `run_relay` against the same persisted cursor and watermarks declares and
   transitions nothing — the replay-safety property.
4. The check-1 episode is driven from `qualified` to `reported` directly through
   `PulseCoreClient.submit_command`, then one more positive `billing_eligibility` row is declared
   against it. The verdict itself still commits (a fresh row), but the paired transition is
   rejected — `reported → qualified` is not a legal edge — so `transition_rejected == 1` and the
   episode's `state_of_record` is unchanged.

See the script's module docstring for the cursor-ordering assumption this leans on: the relay's
mart reader pages on `computed_at` against a persisted, server-side high-water mark, so a
short `declared` count on rerun usually means the mart already holds rows timestamped ahead of
"now" and the persisted cursor needs resetting first.

## Prerequisites

- A dev Postgres holding the migrated ledger schema (`task ledger:migrate` already run against
  it).
- A dev Snowflake mart reachable under the `VERDICT_RELAY_*` credentials
  (`docs/runbooks/billing-state.md` #Poll cadence).
- This repo's Python environment synced: `uv sync --all-packages`.
- Every `VERDICT_RELAY_*` variable `verdict_relay.production.resolve_production_config` reads,
  already exported — the pulse-core base URL and token, and the Snowflake
  account/user/credential/warehouse/database/schema/table — exactly as `task relay:run TARGET=dev`
  expects them. Never printed.

## Running it

```bash
task demo:4
```

equivalent to:

```bash
uv run python scripts/demo/demo4_billing_declare_back.py --target dev --database-url <dev ledger DSN>
```

`--target` (default `dev`, also accepts `staging`/`prod`) labels the receipt only — the
`VERDICT_RELAY_*` variable names carry no target segment, so it never changes which credentials
are read. `--database-url` defaults to demo1's own local compose Postgres
(`postgresql://ledger:...@localhost:5434/ledger`), useful for smoke-testing the script offline
before pointing it at dev.

```bash
uv run python scripts/demo/demo4_billing_declare_back.py --help
```

## Reading the output

Each of the four numbered checks prints what it seeded and observed, followed by the assertion it
proves. A successful run ends with:

```
=== Demo 4: all four live assertions passed ===
```

and exits `0`. A failed assertion prints `FAILED: <what went wrong>` to stderr and the script
exits `1` — the receipt for either outcome is the script's own stdout/stderr.

## Troubleshooting

- **A missing- or conflicting-variable error at startup** — one of the `VERDICT_RELAY_*`
  variables is unset, or two conflicting forms (e.g. password and key-pair) are both set; the
  error names the specific variable.
- **Check 1's `declared` count comes back short** — the persisted mart cursor is already ahead of
  the wall clock this run seeds rows at (see the cursor-ordering note above); reset the cursor
  (`LedgerCursorStore`) before rerunning.
- **A connection error to Postgres** — `--database-url` does not match the dev ledger's DSN, or
  `task ledger:migrate` has not been run against it yet.

## Not part of `task check`

This script needs a live dev Snowflake mart and a dev Postgres, so it is intentionally excluded
from `task check` and CI, and from `task demo:4`'s reach from `check`. Its argument-parsing and
import surface are covered by a smoke-parse test under `tests/`, per the roadmap's demo
convention.
