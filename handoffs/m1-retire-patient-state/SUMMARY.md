# Handoff Summary: m1-retire-patient-state

Collected 3 handoff(s).

## m1-retire-patient-state-task-001

### Spec Updates (proposed; doc-updater owns the files)

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

### PHI posture

`to_state` reaches a log line because it is the projected fact and the receipt is about state.
Nothing else from the payload does — not the clinic value, not a field the handler does not read.
Every log line and receipt is built from envelope identifiers, the state name, sequences and
counts. The tripwire test plants sentinel values in `clinic_id`, `note` and `date_of_birth`,
captures structlog output across a rebuild that mints, skips and parks, and asserts none of them
appears in the logs or in `RebuildReceipt.render()` — while proving the clinic value did reach the
database column it belongs in. `Parked.reason` is a field path or a fixed token by construction.
All fixtures synthetic.

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

## m1-retire-patient-state-task-005

_No spec-relevant updates recorded._

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/m1-retire-patient-state/specs/`
2. Run `openspec validate m1-retire-patient-state` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
