# Handoff Summary: m1-retire-patient-state

Collected 1 handoff(s).

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

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/m1-retire-patient-state/specs/`
2. Run `openspec validate m1-retire-patient-state` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
