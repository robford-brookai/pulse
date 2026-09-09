## Why

Phase 3's third exit criterion (ADR §6) is "M1 retired: no consumer writes
`patients.enrollment_status`". Today graph-projection's `alerts.py` handler still mints a
`patients` row with a hardcoded `'pending'` status on the first alert it sees, the column carries
that default at three layers (SQLAlchemy model, Alembic DDL, the handler), and three read surfaces
present the value as a patient's status. The ledger owns the `enrollment` family, so a projection
table that invents its own subjects and states contradicts ADR §4.3. The `reconciliation-sweeps`
change (in flight) registers this table as the one consumer that cannot cite a ledger sequence and
reports it on every run; this change is the hand-off that report points at. Gate open since
`twenty-projection` archived 2026-08-22, and the FK the bootstrap insert was written to satisfy was
dropped in March (`0016_relax_task_fks.py`), so the insert has been dead weight for six months.

## What Changes

- **`patients` becomes a ledger-fed projection.** A new graph-projection handler consumes the
  `patient-state` feed (never the ledger database, as `twenty-projection` does), mints a `patients`
  row on the first `enrollment` event for a subject and keeps `enrollment_status` equal to the
  catalog's `enrollment` state, applying monotonically on `ledger_seq` and recording that sequence
  on the row. `patient_id` is the canonical patient id the ledger and the Twenty board already
  share. Unresolvable subjects park without failing.
- **The bootstrap insert is deleted** from `alerts.py`. Alerts, tasks, signals, interactions and
  outcomes for a patient the ledger has not minted still land; every `patients` foreign key was
  dropped on 2026-03-17, so nothing needs a row to exist first.
- **The column is read-only and default-free.** The `'pending'` default leaves the model and the
  DDL; a `ledger_seq` column is added; Hasura exposes `patients` as select-only; a CI gate refuses
  any `INSERT` or `UPDATE` against `patients` outside the projection handler. Rows that predate the
  projection keep their value, carry a null `ledger_seq`, and are what `projection-conformance`
  reports as uncitable until genesis mints their subjects.
- **The three read surfaces cut over to the projection.** `patient_graph_summary` is redefined to
  carry `ledger_seq` beside `enrollment_status`; stacte-bridge's schema descriptions say the column
  is projected from the ledger and read-only; the Slack status line renders the catalog state and
  marks a row with no citation as legacy.
- **The asserted status leaves the bus.** `impilo-connector`'s `patient.*` payload no longer
  carries `"enrollment_status": "enrolled"`, a state no consumer applied and the catalog does not
  name.
- **The sweep learns the consumer is citable.** `reconciliation-sweeps`' registry entry for
  `graph-projection-patients` moves from uncitable to `cite_field=ledger_seq` once the projection
  is live, so the conformance sweep compares it row by row like the board.
- **Live execution:** the dev migration, a journal rebuild of the new rows, and the first
  conformance receipt showing `patients` citable are an attended run on a tracking issue.

Out of scope: minting ledger subjects for patients that predate the ledger (that is genesis, BF-4);
retiring the `patients` table or its other columns; any change to what the Twenty board projects;
the survey engine or other producers.

## Capabilities

### New Capabilities
- `patient-state-projection`: the ledger-fed `patients` projection in graph-projection: what
  mints a row, what the status column may hold, how apply orders, how the row cites the ledger, how
  legacy rows are marked, and the read-only contract every other writer must respect.

### Modified Capabilities
- (none) `twenty-ledger-projection`, `projection-rebuild` and the in-flight
  `projection-conformance` are cited, not changed: this change makes `patients` conform to them.

## Impact

- **Code**: `packages/ocean/services/graph-projection/src/handlers/` gains `patient_state.py` and
  loses the bootstrap insert in `alerts.py`; `models.py` and a new Alembic migration under
  `packages/ocean/infra/postgres/versions/` (drop the default, add `ledger_seq`, redefine
  `patient_graph_summary`); `packages/ocean/infra/hasura/apply_metadata.py` (select-only
  permissions on `patients`); `packages/ocean/services/impilo-connector/src/normalizer.py`;
  `packages/ocean/services/stacte-bridge/src/crud_api.py`; `packages/ocean/services/slack-bot/src/slash_commands.py`;
  a new gate test in `packages/ocean/tests/`; the consumer registry in `packages/schedules`.
- **Contracts**: `docs/contracts/publishes.md` gains the projection as a consumer of
  `patient-state`; ADR §6.2 gets its retirement note and the roadmap's Phase 3 row its done mark
  (via `HANDOFF.md`, doc-updater applies).
- **Runtime**: one more handler on graph-projection's existing consumer, one migration on dev's
  graph Postgres, a Hasura metadata apply. No new credential: the handler reads the bus the
  service already reads.
- **Cross-change**: depends on `reconciliation-sweeps` 3.2 (merged) for the registry entry it
  updates; `reconciliation-sweeps` 4.1 (attended) can run before or after this change's 4.1.
- **Rollback**: the migration is reversible (default restored, column dropped, view recreated);
  the handler is a single registration; restoring the bootstrap insert is one revert. Legacy rows
  are never modified, so there is no data to unwind.
