# Runbook — M1 patients projection cutover (m1-retire-patient-state task 4.1)

Attended, one-time dev run that makes the `patients` projection live: apply the schema
migration, route the `patient-state` feed to graph-projection, replay the ledger's `enrollment`
history into `patients`, grant Hasura's read-only surface, and prove the sweep sees the consumer
as citable. Design.md decision 10: one attended run, never a worktree — tracked on its own
GitHub issue, not as a file under `handoffs/`.

**Order matters.** The migration must land before the feed is routed (the handler's `INSERT`
names `ledger_seq`, absent until the migration runs) and the feed must be routed and rebuilt
before Hasura is opened for reads (an empty or half-replayed table read as authoritative is worse
than the table not being readable yet).

## Prerequisites

- Dev graph Postgres credential (`DATABASE_URL` for `packages/ocean`'s graph database — the
  service holding `patients`, not the ledger's own Postgres).
- AWS credential for dev (`AWS_PROFILE=duplo-dev01`, per the `warehouse-sync-revival` pattern) —
  needed to apply the `eventbridge-ocean` Terraform module and to confirm the rule with the CLI.
- The kit's replay credential for the ledger read in step 3 — `PULSE_CORE_BASE_URL` and
  `PULSE_CORE_REPLAY_TOKEN` (`pulse_core.replay`), the same pair `task projection:rebuild` uses
  for the board projection. A read over HTTP; never a ledger DSN.
- Hasura admin secret for dev (`HASURA_URL`, `HASURA_GRAPHQL_ADMIN_SECRET`).

## Steps

1. **Apply migration 0021.** `packages/ocean/infra/postgres/versions/0021_patients_ledger_seq.py`
   drops `enrollment_status`'s server default, adds `ledger_seq BIGINT NULL`, and recreates
   `patient_graph_summary` with `ledger_seq` in the select and group-by (design.md decisions 3, 7):

   ```bash
   cd packages/ocean/infra/postgres
   DATABASE_URL=<dev graph postgres> uv run --project ../.. alembic upgrade head
   ```

   PASS: `alembic upgrade head` exits 0 and `alembic current` shows `0021_patients_ledger_seq` as
   the head revision. Legacy rows keep their status and read `ledger_seq IS NULL` — do not touch
   them (design.md decision 5).

2. **`terraform apply` the `eventbridge-ocean` module** so graph-projection's rule includes
   `patient-state` (design.md decision 11; `packages/ocean/infra/terraform/modules/eventbridge-ocean`,
   generated pattern in `packages/ocean/infra/terraform/generated/event_catalog.auto.tfvars.json`).
   This is the `destructive_ops` lane step (WORKFLOW.md), run against dev's Terraform state, not
   from this worktree.

   PASS, confirmed from the CLI, not assumed from the plan:

   ```bash
   aws events describe-rule --name duploservices-dev01-brook-ocean-graph-projection \
     --event-bus-name duploservices-dev01-brook-ocean --query EventPattern --output text
   ```

   prints an `EventPattern` whose `detail-type` list now includes `"patient-state"` alongside
   graph-projection's existing domains. Cross-check it agrees with
   `ocean_broker.catalog.consumer_rule_pattern("graph-projection")` computed from the tree at the
   applied commit — the same assertion `test_terraform_consumers.py` makes offline, reconfirmed
   against the real rule. Until this step lands, the handler from step 3 is inert on dev — the
   documented safe failure, not a defect (design.md decision 11).

3. **Rebuild:** replay every committed `enrollment` event into `patients` before anyone reads
   the projected rows (design.md decisions 10 and 12):

   ```bash
   DATABASE_URL=<dev graph postgres> \
   PULSE_CORE_BASE_URL=<dev command api> PULSE_CORE_REPLAY_TOKEN=<dev replay token> \
     task projection:rebuild-patients TARGET=dev OPERATOR=<who>
   ```

   The CLI is `packages/ocean/services/graph-projection/src/rebuild_patients.py` (task 3.3). It
   reads each subject's committed events through the ledger's replay route over HTTP
   (`PulseCoreClient.subject_history`, paged to exhaustion) and folds them through the same
   `handle_patient_state` the live consumer applies, so this is a real assertion of monotonicity,
   not a second implementation to trust separately. Scope is every `patient_id` already in
   `patients` — the legacy rows adoption exists for — plus any subject with no row yet, named as
   `SUBJECT="pt-a pt-b"`. Safe to rerun: a second pass with no intervening events writes nothing
   and counts every event as a skip.

   PASS: the printed `RebuildReceipt` (counts only — events read, subjects, rows written, skipped
   stale, parked) shows rows written for the subjects the ledger has minted `enrollment` events
   for, and exit 0. Parked is expected and counted, never a failure: it is subjects the ledger has
   no history for yet (legacy rows awaiting genesis, which keep their status and null `ledger_seq`)
   plus any event that resolved to no canonical patient id. Exit 2 means a variable is unset and
   nothing was read or written; the message names every missing one.

4. **Apply Hasura metadata** — select-only grant on `patients` for every service role, columns
   including `ledger_seq` (design.md decision 4; `packages/ocean/infra/hasura/apply_metadata.py`):

   ```bash
   HASURA_URL=<dev hasura> HASURA_GRAPHQL_ADMIN_SECRET=<dev admin secret> \
     uv run python packages/ocean/infra/hasura/apply_metadata.py
   ```

   PASS: `Summary: N succeeded, 0 failed` and the `patients` select permission is present for
   every role in `SERVICE_ROLES` — no role gets `INSERT`/`UPDATE`, matching the gate
   (`packages/ocean/tests/gates/test_patients_read_only.py`).

5. **Run the `enrollment` conformance sweep once**, now that the registry has flipped it citable
   (task 3.1; design.md decision 9):

   ```bash
   schedules reconcile-sweep --family enrollment
   ```

   PASS: the receipt line's `graph-projection-patients` entry reports `agreements`/`divergences`
   per subject — no longer the `uncitable` class report task 3.1 retired. Legacy rows (null
   `ledger_seq`) still count `uncitable` per row; that is expected until genesis adopts them
   (design.md decision 5), not a sweep defect.

6. **Post the receipt** on the tracking GitHub issue — subject keys (capped at 200, true total
   beside the cap) and counts only, from steps 3 and 5, never a payload value or a payer
   identifier. Never a file under `handoffs/`.

## Verification the runbook itself asserts (task 4.1's stated tests)

- The consumer rule pattern lists `patient-state` (step 2).
- Zero `INSERT INTO patients` from graph-projection logs outside the handler during the run —
  watch the service logs through steps 3-5; the gate test already proves this statically, the
  attended run reconfirms it live.
- `patient_graph_summary` returns `ledger_seq` for projected rows (step 1, spot-checked after
  step 3).
- The sweep receipt shows the consumer as citable (step 5).

## Rollback

Downgrade the migration (`alembic downgrade -1` from `packages/ocean/infra/postgres`, restoring
the default, dropping `ledger_seq`, recreating the pre-0021 view); revert the `terraform apply` by
re-applying the module from the pre-change commit so `patient-state` drops out of
graph-projection's rule; the handler is not separately "unregistered" — with the rule reverted it
simply stops receiving events. Legacy rows were never modified by any of this, so there is nothing
to unwind on the data side (design.md Migration Plan).
