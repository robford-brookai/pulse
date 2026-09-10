# Runbook — M1 patients projection receipt run (m1-retire-patient-state task 4.1)

The attended run that proves the retired patient-state derivation is replaced end to end:
migration 0021, the ledger-fed rebuild of `patients`, and the read-only Hasura grant. It runs on
the OCEAN compose stack, because the dev01-brook tenant hosts no graph-projection, Hasura or OCEAN
graph Postgres (design.md decision 13). The rebuild still reads the dev ledger's replay route over
HTTP, so the receipt exercises the real journal. Receipts go on the tracking issue (#450), counts
and subject keys only, never a file under `handoffs/`.

## Prerequisites

- Docker running, and `packages/ocean/infra/docker-compose.yml` at a main checkout that includes
  #440, #445 and #451 (the compose `graph-projection` entry builds from the repo root).
- The kit's replay credential for the ledger read in step 3: `PULSE_CORE_BASE_URL` (the dev
  command API) and `PULSE_CORE_REPLAY_TOKEN` (`pulse_core.replay`), the same pair
  `task projection:rebuild` uses for the board projection. A read over HTTP; never a ledger DSN.
  Retrieval: `docs/process/env-vars-retreival.md` §3, key `PULSE_CORE_REPLAY_TOKEN` in the Duplo
  secret `pulse-ledger-api-secret` (dev01-brook).
- No dev graph database credential exists; the compose Postgres is the target. Its DSN, from the
  compose file's defaults, is `postgresql+asyncpg://ocean:changeme@localhost:5433/ocean` and the
  compose Hasura listens on `http://localhost:8090` with admin secret `changeme_admin_secret`.
  Override both with `POSTGRES_PASSWORD` and `HASURA_GRAPHQL_ADMIN_SECRET` if you change them.

## Steps

1. **Bring up the graph stack and apply migration 0021.** The compose `migrate` service runs the
   Alembic chain, which now ends at 0021 (drops `enrollment_status`'s server default, adds
   `ledger_seq BIGINT NULL`, recreates `patient_graph_summary` with `ledger_seq`; design.md
   decisions 3, 7):
   ```bash
   cd packages/ocean/infra
   docker compose up -d postgres migrate hasura hasura-init graph-projection
   docker compose logs migrate | tail -5
   ```
   PASS: the `migrate` log ends at `0021_patients_ledger_seq` and
   `DATABASE_URL=postgresql://ocean:changeme@localhost:5433/ocean uv run --project ../.. alembic -c postgres/alembic.ini current`
   (run from `packages/ocean/infra`) prints `0021_patients_ledger_seq (head)`. A legacy row, if you
   seed one, keeps its status and reads `ledger_seq IS NULL` (design.md decision 5).
2. **Consumer rule: deferred.** In the environment that hosts graph-projection, the
   `eventbridge-ocean` module's `terraform apply` adds `patient-state` to graph-projection's rule
   (design.md decision 11) and the confirmation is
   `aws events describe-rule --name <bus>-graph-projection --event-bus-name <bus> --query EventPattern --output text`
   listing `"patient-state"`. dev01-brook has no such consumer running, so this step is recorded on
   the tracking issue as deferred to `environment-matrix` (design.md decision 13), not run here.
   Until it runs somewhere, the live handler is inert there, the documented safe failure.
3. **Rebuild:** replay every committed `enrollment` event into the compose `patients` from the dev
   ledger (design.md decisions 10 and 12):
   ```bash
   DATABASE_URL=postgresql+asyncpg://ocean:changeme@localhost:5433/ocean \
   PULSE_CORE_BASE_URL=<dev command api> PULSE_CORE_REPLAY_TOKEN=<dev replay token> \
     task projection:rebuild-patients TARGET=dev OPERATOR=<who>
   ```
   Scope is every `patient_id` already in `patients` plus any subject named as
   `SUBJECT="pt-a pt-b"`; on a fresh compose Postgres the table is empty, so name the subjects
   the dev ledger has minted `enrollment` events for (the sweep receipts on #435 or
   `pulse_core.client.PulseCoreClient.subject_history` list them). Safe to rerun: a second pass with
   no intervening events writes nothing and counts every event as a skip.
   PASS: the printed `RebuildReceipt` (events read, subjects, rows written, skipped stale, parked)
   shows rows written for the named subjects and exit 0; a rerun shows rows written 0. Parked is
   counted, never a failure: subjects the ledger has no history for. Exit 2 means a variable is
   unset; the message names every missing one.
4. **Apply Hasura metadata** to the compose Hasura — select-only on `patients` for every service
   role, columns including `ledger_seq` (design.md decision 4):
   ```bash
   HASURA_URL=http://localhost:8090 HASURA_GRAPHQL_ADMIN_SECRET=changeme_admin_secret \
     uv run python packages/ocean/infra/hasura/apply_metadata.py
   ```
   PASS: `Summary: N succeeded, 0 failed`, and the `patients` select permission is present for every
   role in `SERVICE_ROLES` with `ledger_seq` in its column list; no role gets `INSERT`/`UPDATE`,
   matching the gate (`packages/ocean/tests/gates/test_patients_read_only.py`).
5. **Run the `enrollment` conformance sweep once** (reconciliation-sweeps; design.md decision 9):
   ```bash
   schedules reconcile-sweep --family enrollment
   ```
   Before reconciliation-sweeps task 3.4 lands, the CLI reports `no_consumers` for every ledger
   family; record that line as the step's receipt. After 3.4, the receipt names
   `graph-projection-patients` as `unconfigured` on dev01 (no graph database there) unless
   `SCHEDULES_GRAPH_DATABASE_URL` points at the compose Postgres, in which case projected rows
   compare per subject and legacy rows count `uncitable`.
6. **Post the receipt** on the tracking issue: the `migrate` tail, the `RebuildReceipt` from the
   first and second pass, the Hasura summary, the sweep line, and the deferred note for step 2.
   Subject keys (capped at 200, true total beside the cap) and counts only, never a payload value.

## Verification the runbook itself asserts (task 4.1's stated tests)

- `alembic current` is 0021 and `patient_graph_summary` returns `ledger_seq` for projected rows
  (step 1, spot-checked after step 3).
- Zero `INSERT INTO patients` from the compose graph-projection logs outside the handler during
  steps 3–5 (`docker compose logs graph-projection | grep -i 'insert into patients'` is empty);
  the gate proves this statically, the run reconfirms it live.
- The rebuild receipt shows rows written on the first pass and none on the second (step 3).
- The Hasura select permission lists `ledger_seq` for every service role (step 4).

## Rollback

The stack is local: `docker compose down -v` from `packages/ocean/infra` discards it. Nothing in
this run touches dev01 or production; the deferred consumer rule is applied, and rolled back, in
the environment that hosts graph-projection.
