# Handoff Summary: critical-path-verification

Collected 1 handoff(s).

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

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/critical-path-verification/specs/`
2. Run `openspec validate critical-path-verification` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
