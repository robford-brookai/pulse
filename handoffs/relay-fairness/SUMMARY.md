# Handoff Summary: relay-fairness

Collected 1 handoff(s).

## relay-fairness-task-001

### Added Requirements

None — this task adds the scan primitives the "Independent ready subjects receive bounded fair
service" requirement (`openspec/changes/relay-fairness/specs/ledger-distribution/spec.md`) already
describes. No wording change needed.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. `pulse_ledger.relay` gained `candidate_subjects()`, `ScanState`, `SubjectStatus`,
`ScanResult`, and `scan_pass()` as pure additions alongside the existing `pending_rows()` /
`relay_once()` — nothing about `relay_once`'s current selection or `relay_worker.py` changed in
this task; wiring the scan into selection is task 1.2.

## New Scenarios

None beyond what `traceability.json` already maps to this task's two spec scenarios ("Skewed
backlog cannot starve an independent subject", "Locked and backing-off heads do not monopolize
scans").

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/relay-fairness/specs/`
2. Run `openspec validate relay-fairness` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
