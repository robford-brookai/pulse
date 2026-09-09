## Context

See proposal.md for motivation. What exists: `packages/ocean/services/graph-projection/src/handlers/alerts.py:35-42`
mints `patients` rows with `'pending'` (`INSERT ... ON CONFLICT DO NOTHING`), the only writer; the
default is repeated in `src/models.py:24` (`default="pending"`) and
`infra/postgres/versions/0003_graph_tables.py:25` (`server_default="pending"`). Every foreign key
onto `patients` was dropped by `0016_relax_task_fks.py` on 2026-03-17, so the insert's own comment
("ensure FK constraint is satisfied") has been stale for six months. Read surfaces:
`patient_graph_summary` (`0006_pgvector.py:61-85`, a materialized view grouped by
`enrollment_status` with a unique index), stacte-bridge `crud_api.py:25-26,53-54` (LLM-facing
schema descriptions), slack-bot `slash_commands.py:193-194,246` (Hasura query and the
`*Status:*` line). Hasura tracks `patients` and three relationships (`infra/hasura/apply_metadata.py`).
`impilo-connector/src/normalizer.py:241` asserts `"enrollment_status": "enrolled"` into a
`patient.*` payload nobody applies. The ledger's `enrollment` family (catalog 1.1.0) has states
`pending_start`, `active`, `on_hold`, `ended`; the board projection (`twenty-projection`) shows the
pattern to copy: feed-fed, monotonic on `(subject_id, ledger_seq)`, parks unresolvable subjects,
rebuilds from the journal. `reconciliation-sweeps` (in flight) registers `graph-projection-patients`
as an uncitable consumer.

## Goals / Non-Goals

**Goals:** satisfy ADR §6.2's four clauses (rows only from projection, three surfaces cut over,
column read-only, insert deleted) with the smallest surface; make `patients` a citable consumer so
the conformance sweep can compare it; keep legacy rows honest rather than silently rewritten.

**Non-Goals:** minting ledger subjects for pre-ledger patients (genesis, BF-4); removing the
`patients` table or its `clinic_id`/`enrolled_at` columns; changing the board projection; moving
graph-projection onto the connector kit (it is an ocean service the program retires, not a
connector).

## Decisions

1. **A projection handler inside graph-projection, on its existing consumer.** graph-projection
   already consumes bus events through per-domain handlers; `patient_state.py` joins them and
   subscribes to `patient-state` for `enrollment` subjects. Alternative rejected: a new kit-based
   connector package, which would add a fourth ledger consumer to run and deploy for a table the
   program eventually retires.
2. **Mint on the first `enrollment` event, keyed by the canonical patient id.** The `enrollment`
   subject resolves to the canonical patient id the ledger and the board share (the same lookup
   `twenty-projection` performs); that id is what `patients.patient_id` holds for projected rows.
   Legacy rows keyed by other identifiers are not re-keyed; they wait for genesis to adopt them
   (decision 5). Alternative rejected: minting on `referral` or `person` events, which would create
   rows for patients with no enrollment, the very thing the old bootstrap did with alerts.
   **Addendum (task 1.1).** `clinic_id` on mint takes `payload["clinic_id"]` when it is a
   non-empty string, else the sentinel `"unknown"` (named constant `UNSCOPED_CLINIC_ID`) — the
   same value the retired bootstrap insert wrote, so projected and legacy rows share one marker
   for "no clinic scope known." Never derived from `program` (patient × program is not a clinic
   relationship). Never touched on adopt or update. `clinic_id` stays a legacy, uncitable column
   until the table retires; the spec's "a hardcoded default never appears" scenario is scoped to
   `enrollment_status` only. The `enrollment_status` catalog-family clause is guaranteed upstream
   by ledger write-path validation against the catalog — the projection does not re-encode the
   family — matching the parallel note now in the spec. The canonical-id lookup is implemented as
   an injectable `CanonicalIdResolver`, defaulting to `resolve_canonical_patient_id`: it is the
   one seam where the projection decides which id a `patients` row is keyed by.
3. **The column keeps its name and gains a citation.** `enrollment_status` stays (three surfaces
   and Hasura know it), loses both defaults (model and DDL), and is joined by `ledger_seq BIGINT
   NULL`. NOT NULL stays because every projected write supplies a value and legacy rows already
   have one. Alternative rejected: dropping the column and pointing surfaces at the command API,
   which gives stacte-bridge and slack-bot ledger credentials they do not need and breaks the
   materialized view's single-database join.
4. **Read-only is enforced twice.** A repository gate test greps `packages/ocean` for
   `INSERT INTO patients` and `UPDATE patients` outside `handlers/patient_state.py` and fails
   naming the file; Hasura metadata grants select-only on `patients` for every role the services
   use. The gate catches the next developer; the grant catches the next operator.
5. **Legacy rows are marked, not migrated.** The migration adds `ledger_seq` as null for existing
   rows and touches no status value. A null citation is the marker; the sweep counts those rows as
   uncitable; the first ledger event for the row's canonical id adopts it. Alternative rejected:
   setting legacy statuses to `unknown`, which destroys the one fact those rows carry (that the old
   handler saw an alert) and pretends the migration knows more than it does.
6. **Alerts for unminted patients are orphans, not row-minters.** With every FK dropped, an alert
   for a patient the ledger has not minted lands and shows up in the conformance sweep's `orphan`
   count for the `patients` consumer. That is the correct signal: either genesis has not reached
   that patient or the alert names a patient the ledger does not know.
7. **`patient_graph_summary` is recreated, not altered.** Materialized views cannot be altered in
   place; the migration drops and recreates it with `ledger_seq` in the select and group-by and
   recreates the unique index. Readers of the view see one additional column.
8. **The normalizer's asserted status is deleted, not mapped.** `"enrolled"` is not a catalog
   state and no consumer applied it; mapping it to `active` would turn a dead field into a live
   producer of state, the §4.4 violation the producer-ingress gate exists to stop.
9. **The sweep registry flips to citable in this change, not in `reconciliation-sweeps`.**
   `reconciliation-sweeps` shipped the uncitable entry (its 3.2); the entry's `cite_field` and
   `owning_change` change here, in the change that earns it, after the projection is live on dev.
10. **Live execution is one attended run.** Apply the migration on dev's graph Postgres, run the
    handler's rebuild path over the journal for `enrollment` subjects so projected rows exist before
    anyone reads them, apply Hasura metadata, then run the conformance sweep once and post the
    receipt. Never a worktree.
11. **The feed reaches graph-projection through the event catalog, not a new queue.**
    graph-projection's EventBridge rule is generated from `CONSUMER_DOMAINS` in
    `ocean_broker/catalog.py`; at proposal time it listed ten domains and not `patient-state`, so
    the handler in decision 1 would never receive an event (event-store and warehouse-sync already
    subscribe to the domain). Adding the domain to the existing consumer keeps one queue and one
    consumer loop; the alternative, a dedicated queue and rule for the projection, is the fourth
    deployable decision 1 rejected. Until the regenerated rule is applied on dev (task 4.1) the
    handler is inert there, which is the safe failure. Found 2026-09-09 reviewing task 1.1's PR;
    added as task 1.4.
12. **The rebuild is an operator command, not an adapter written on the day.** `patient_state.rebuild`
    shipped (task 1.1) with a `JournalReader` Protocol and a test fixture only; the runbook (task
    3.2) found nothing committed to invoke on dev. Task 3.3 adds `rebuild_patients.py` and
    `task projection:rebuild-patients`, mirroring `twenty_projection.rebuild`: history over HTTP
    through `pulse_core.client.PulseCoreClient.subject_history` with the `pulse_core.replay`
    credential, never a ledger DSN. The ledger's read surface is per subject, so scope is every
    `patient_id` already in `patients` plus an optional operator list; subjects the ledger mints
    after the rule is applied arrive live. Per-subject order is enough because the monotonic guard
    is per `patient_id`. `pulse-core` becomes a graph-projection dependency for this module only;
    the live handler keeps importing nothing from it (decision 2's validation note stands).
    Alternative rejected: an operator-written adapter at run time, which is untested code touching
    dev data. Found 2026-09-09 reviewing task 3.2's PR.

## Data model and API surface

- `patients`: existing columns; `enrollment_status TEXT NOT NULL` (defaults removed); new
  `ledger_seq BIGINT NULL`. Projected rows: status ∈ catalog `enrollment` states, `ledger_seq` set.
  Legacy rows: any status, `ledger_seq` null.
- Handler `patient_state.apply(event) -> Applied | Skipped | Parked`, monotonic on
  `(patient_id, ledger_seq)`; `rebuild(journal_reader)` replays `enrollment` events in sequence.
- `patient_graph_summary`: existing columns plus `ledger_seq`.
- Gate: `packages/ocean/tests/gates/test_patients_read_only.py`.
- Registry entry: `Consumer("graph-projection-patients", families=("enrollment",),
  reader=RowCountReader→PatientsReader, cite_field="ledger_seq", owning_change=None)`.

## Risks / Trade-offs

- [Canonical id resolution fails for some subjects] → park-and-count, as the board does; parked
  subjects appear in the handler's receipt and never block the consumer.
- [The materialized view recreate locks readers briefly on dev] → run in the attended window;
  `REFRESH ... CONCURRENTLY` afterwards as today.
- [The consumer rule is applied before the migration] → the handler's INSERT names `ledger_seq`
  and fails on the missing column; the runbook orders migration, then `terraform apply`, then rebuild.
- [A legacy `patients` row has no ledger history yet] → the rebuild counts it as parked and leaves
  it uncitable; genesis (BF-4) adopts it later. The receipt names the count, never the row.
- [Hasura permission change breaks a writer nobody knew about] → the gate test runs first and
  would have named it; the attended run watches graph-projection logs for permission errors.
- [Legacy rows dominate the uncitable count for months] → expected until genesis; the receipt
  separates legacy (null citation) from newly parked rows so the trend is readable.
- [Two changes in flight collide] → `reconciliation-sweeps` has only 4.1 (attended) left; this
  change's registry edit (3.1) is a one-line change in `packages/schedules` after that change's
  code is on main.

## Migration Plan

Wave 0 lands the handler, the migration and the model change together with the insert deletion and
the normalizer fix, all behind tests. Wave 1 enforces read-only (gate, Hasura) and cuts the three
read surfaces. Wave 2 flips the sweep registry entry and documents (HANDOFF for the ADR note and
roadmap). Wave 3 is the attended dev run. Rollback: downgrade the migration (restores the default,
drops `ledger_seq`, recreates the old view), unregister the handler, revert the insert deletion;
legacy rows were never modified.

## Open Questions

- Whether `enrolled_at` should be projected from the `active` transition's `effective_at`. Cheap to
  add later; changes no spec here.
