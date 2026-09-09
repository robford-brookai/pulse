# Handoff Summary: m1-retire-patient-state

Collected 8 handoff(s).

## m1-retire-patient-state-task-001

## Spec Updates

1. **design.md decision 2 addendum — `clinic_id` source on mint.** `patients.clinic_id` is
   `TEXT NOT NULL` with no default (`0003_graph_tables.py:25`) and the ledger does not assert it,
   so a mint needs a rule the spec does not state. Adjudicated with the coordinator: take
   `payload["clinic_id"]` when it is a non-empty string, else the literal sentinel `"unknown"` —
   the same value the retired bootstrap insert wrote, so projected and legacy rows share one "no
   clinic scope known" marker. Never derived from `program` (patient × program is not a clinic).
   Never touched on adopt or update. `clinic_id` stays a legacy, uncitable column until the table
   retires; the spec's "a hardcoded default never appears" is scoped to `enrollment_status`.
   Implemented as the named constant `UNSCOPED_CLINIC_ID`.

2. **Spec note — the resolver is a named seam.** "A subject that does not resolve to a canonical
   patient id SHALL park" is implemented as an injectable `CanonicalIdResolver`, defaulting to
   `resolve_canonical_patient_id`: the `enrollment` subject key *is* the canonical patient id, the
   lookup `twenty-projection` performs when it filters the board on `canonicalPatientId`
   (design.md decision 2). Stated as a seam rather than assumed inline because it is the one place
   the projection decides which id a `patients` row is keyed by.

3. **Spec wording addendum — catalog membership is guaranteed upstream, not re-checked here.**
   The clause "`enrollment_status` SHALL hold only names from the catalog's `enrollment` family
   (`pending_start`, `active`, `on_hold`, `ended`) for projected rows" should read, with the
   addition: "*(guaranteed by the ledger write-path validation against the catalog; the projection
   does not re-encode the family)*". Design decision 2 gains the same note. A first draft of this
   handler carried an `ENROLLMENT_STATES` frozen set to enforce the clause locally and the §4.4
   producer-ingress gate flagged it correctly: the projection writes `to_state` verbatim, and a
   second encoding of the family inside `packages/ocean` is the drift the gate exists to prevent.
   No suppression entry was added and `pulse-core` was **not** added as a graph-projection
   dependency (that would be a plan amendment, out of 1.1 scope). The gate is green on the tree.

4. **Not projected, unchanged.** `enrolled_at` stays null-or-legacy (design.md Open Questions —
   whether to project it from the `active` transition's `effective_at` changes no spec here).

## m1-retire-patient-state-task-002

## Spec Updates

No spec updates needed. This task (1.2 Schema) implemented the migration and model change
exactly as design.md decisions 3 and 7 specify.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. `packages/ocean/infra/postgres/versions/0021_patients_ledger_seq.py` drops
`patients.enrollment_status`'s server default, adds `ledger_seq BIGINT NULL`, and drops and
recreates `patient_graph_summary` with `ledger_seq` in the select and group-by plus its unique
index. `models.py`'s `Patient` loses `default="pending"` and gains `ledger_seq`.

## New Scenarios

None.

## m1-retire-patient-state-task-003

## Spec Updates

No spec updates needed. This task (1.3) implements the two spec clauses exactly as stated:
"Only the ledger projection mints or updates a patient row" and "No asserted enrollment state
travels the bus from a producer."

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. `packages/ocean/services/graph-projection/src/handlers/alerts.py` drops the STEP 1
`patients` bootstrap insert `handle_alert_created` carried; the handler now writes only `alerts`
and `audit_log`. `packages/ocean/services/impilo-connector/src/normalizer.py`'s `patient.*` payload
branch drops the `enrollment_status` key, leaving `patient_id` and `source_patient_type`.

## New Scenarios

None. Both scenarios below were already in the spec; this task is what makes them true.

- "An alert for an unknown patient mints nothing": covered by a new sqlite-backed test,
  `test_alert_for_an_unknown_patient_mints_no_patients_row`.
- "The normalizer emits no status": covered by a new test,
  `test_patient_payload_carries_no_enrollment_status`.

## m1-retire-patient-state-task-005

_No spec-relevant updates recorded._

## m1-retire-patient-state-task-006

## Spec Updates

No spec updates needed. This task (3.1 Registry) implemented the flip to citable exactly as
spec "The projection is a citable consumer" and design.md decision 9 describe.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. `schedules.consumer_registry.build_consumers` now registers `graph-projection-patients`
with `cite_field="ledger_seq"` and `owning_change=None` (was `cite_field=None`,
`owning_change="m1-retire-patient-state"`, `reconciliation-sweeps`'s day-one entry), reading
through the new `schedules.sweep_readers.PatientsReader` — `(patient_id, enrollment_status,
ledger_seq)` rows, `ledger_seq` nullable for a legacy row, over the same `FamilyRowSource` seam
`LandingReader` already uses. The now-unused `PATIENTS_OWNING_CHANGE` constant was removed rather
than left dead, per design.md decision 9 ("owning_change=None").

## New Scenarios

None. The existing spec scenarios ("A projected row agrees with the ledger", legacy-row handling)
are exercised end to end in `tests/test_consumer_registry.py`
(`TestGraphProjectionPatientsIsCompared`) via the registered consumer, and per-reader in
`tests/test_sweep_readers.py`.

## m1-retire-patient-state-task-1-4

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. Implementation matches design.md decision 11 exactly: `patient-state` added to
`CONSUMER_DOMAINS["graph-projection"]` in `packages/ocean/libs/ocean-broker/src/ocean_broker/catalog.py`,
regenerated into `packages/ocean/infra/terraform/generated/event_catalog.auto.tfvars.json`.

## New Scenarios

None.

## m1-retire-patient-state-task-2-1

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. Implemented as decision 4 describes: a repository gate plus a Hasura select-only grant.
One addition beyond decision 4's text, not a drift from it: `apply_metadata.py` had no per-role
permission machinery before this task (it only tracked tables and relationships), so this task
introduced `SERVICE_ROLES` and `PATIENTS_SELECT_COLUMNS` as the first per-role grant in that file.
The role list (`graph-projection`, `control-plane`, `slack-bot`, `impilo-connector`,
`stacte-bridge`, `sim-driver`) is every ocean service in `infra/docker-compose.yml` besides
`hasura`/`localstack`/connector-kit infra services; if a deployment's actual Hasura role names
differ, `SERVICE_ROLES` is the one place to reconcile them.

## New Scenarios

None — the two scenarios under "Only the ledger projection mints or updates a patient row" were
implemented as written.

## m1-retire-patient-state-task-3-2

## Spec Updates

None. This task is docs-only, no spec-relevant behavior changed.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None from this task's own scope. One gap surfaced while writing the runbook, worth flagging for
whoever scopes task 4.1: `graph_projection.handlers.patient_state.rebuild()` has no committed
production `JournalReader` implementation or CLI wrapper — unlike the board projection's
`task projection:rebuild` (`twenty_projection.rebuild`), this package only ships the `Protocol`
and a test fixture. Task 4.1's tasks.md entry says "run `patient_state.rebuild` over the journal"
as if the plumbing exists; it doesn't yet. Documented as a runbook step that needs an
operator-written adapter for that run rather than a committed target — see
`docs/runbooks/m1-patients-projection.md` step 3 — but if 4.1 wants a committed CLI, that is
additional scope not currently sized anywhere.

## New Scenarios

None.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/m1-retire-patient-state/specs/`
2. Run `openspec validate m1-retire-patient-state` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
