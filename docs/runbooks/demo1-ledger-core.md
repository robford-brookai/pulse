# Runbook: Demo 1 — pulse-ledger-core (Phase 1 breakpoint)

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints),
this is the final task of the phase-closing change (`pulse-ledger-core`, task 5.3). It runs
against LocalStack, Postgres, and fixtures only — never PHI, never live prod.

Script: `scripts/demo/demo1_ledger_core.py`.

## What it shows

1. A legal command commits and lands on the outbox's queue.
2. An illegal command rejects with the catalog's reason and version.
3. A replay (the same idempotency key twice) returns the original event id, and exactly one event
   is stored.
4. Independently folding a subject's raw committed events equals its co-committed `current_state`
   row after a mixed history — forward, backdated, reversal (wraps the task 5.1 harness).

## Prerequisites

- Docker, with `docker compose` available.
- This repo's Python environment synced: `uv sync --all-packages` (or `task check` will already
  have done this once).
- Nothing else — the script brings the LocalStack/Postgres stack up itself.

## Running it

```bash
uv run python scripts/demo/demo1_ledger_core.py
```

This runs `docker compose -f packages/ocean/infra/docker-compose.yml up -d --wait` against
`localstack`, `ledger-postgres`, `ledger-migrate`, `localstack-init`, and `ledger-relay` (naming
`ledger-relay` alone would work too — compose starts its dependency chain — but the full list
makes the bring-up step legible in the script's own output), waits for them to report healthy or
complete, then runs the four steps above against the running stack, printing each assertion as it
passes. The script exits nonzero the moment any assertion fails.

If the stack is already running (a previous run, or brought up by hand), skip the bring-up step:

```bash
uv run python scripts/demo/demo1_ledger_core.py --skip-compose-up
```

Every other knob has a default matching `packages/ocean/infra/docker-compose.yml`'s own
conventions (`--database-url`, `--aws-endpoint-url`, `--event-bus-name`, `--consumer`,
`--queue-timeout`) — see `--help` for the full list:

```bash
uv run python scripts/demo/demo1_ledger_core.py --help
```

## Reading the output

Each of the four numbered steps prints what it committed or observed, followed by the assertion it
proves. A successful run ends with:

```
=== Demo 1: all four assertions passed ===
```

and exits `0`. A failed assertion prints `FAILED: <what went wrong>` to stderr and the script exits
`1` — the receipt for either outcome is the script's own stdout/stderr, captured whole and attached
to `DNA-784` before the change is archived.

## Tearing down

The compose stack is left running after the script exits (some other demo or manual poking may
still want it). To tear it down:

```bash
docker compose -f packages/ocean/infra/docker-compose.yml down
```

## Troubleshooting

- **`docker compose ... up` fails or times out** — Docker is not running, or a previous stack is in
  a bad state. `docker compose -f packages/ocean/infra/docker-compose.yml down -v` and retry.
- **Step 1 times out waiting on the queue** — the `ledger-relay` service is not relaying. Check
  `docker compose -f packages/ocean/infra/docker-compose.yml logs ledger-relay`; it depends on
  `ledger-migrate` and `localstack-init` completing successfully first.
- **A connection error to Postgres** — `ledger-postgres` is not yet accepting connections, or
  `--database-url` does not match its host-mapped port (`5434`) or the `LEDGER_POSTGRES_PASSWORD`
  it was brought up with. Re-run with `--skip-compose-up` only once `docker compose ps` shows
  `ledger-postgres` healthy.

## Not part of `task check`

This script needs a live LocalStack and Postgres, so it is intentionally excluded from `task
check` and CI. `tests/test_demo1_ledger_core.py` covers what does not need that stack: the script
parses, its argument surface behaves, and `--help` exits cleanly with no live network.
