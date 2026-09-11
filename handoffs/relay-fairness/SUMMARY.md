# Handoff Summary: relay-fairness

Collected 2 handoff(s).

## critical-path-verification-task-001

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. Implemented per design.md decision 1 and tasks.md 1.1: `scripts/critical_pg_gate.py`
provides `Mode.REQUIRED`/`Mode.OPTIONAL`, `ensure_pg_binaries` (fails setup in required mode,
skips visibly in optional mode), and the selector (`run_critical_suite`/`evaluate_junit`) that
fails required mode on zero critical collection or any skipped mandatory case. Discovery is
PATH/`PULSE_PG_BINDIR`-only (no host-layout globbing), since CI pins/provisions the server in
1.2. Nothing is wired into `Taskfile.yml`, `pyproject.toml`, or CI — that is 1.2's serial task on
those shared roots.

## New Scenarios

None — this task's three scenarios ("Missing database prerequisite fails required mode", "Empty
or skipped critical collection fails", plus optional-mode preservation) are already in
`specs/critical-path-gates/spec.md` and are covered by
`tests/test_critical_postgres_gate.py` via real subprocess pytest runs (not YAML-only checks).

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
