# Handoff Summary: critical-path-verification

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

## critical-path-verification-task-002

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. Implemented per design.md decisions 1, 3 and 4, and tasks.md 1.2:

- **Postgres provisioned and pinned in CI.** `.github/workflows/main.yml`'s `quality` job installs
  `postgresql-16` via apt before `task check`, exports `PULSE_PG_BINDIR`, and sets
  `PULSE_CRITICAL_PG_MODE=required` on the `task check` step so the critical gate fails closed
  there. Locally the mode is unset and defaults to optional, so a dev without a local Postgres
  still gets a green `task check`.
- **Required mode wired into the existing quality contract.** New `scripts/critical_gate_evidence.py`
  (task 1.2) runs `critical_pg_gate.run_critical_suite` against `packages/pulse-ledger/tests` and
  `packages/pulse-core/tests`, wired in as `task test:critical`, itself a dependency of `task test`
  (and therefore `task check`).
- **Real invariant tests marked `@pytest.mark.critical`.** Six pre-existing, already-Postgres-backed
  tests in `packages/pulse-ledger/tests` — one per invariant category the spec names — are now
  marked: `test_migration_0005.py::test_downgrade_restores_the_0004_vocabulary` (migration),
  `test_commit.py::test_an_injected_failure_after_the_event_leaves_no_partial_write` (atomicity),
  `test_commit.py::test_the_commit_path_runs_as_the_service_role` (role),
  `test_commit.py::test_a_reversal_references_the_voided_event_preserves_history_and_folds_state_back`
  (reversal), `test_idempotent_commit.py::test_the_same_key_arriving_twice_at_once_still_produces_one_event`
  (concurrency), `test_idempotent_commit.py::test_a_retry_with_the_same_key_replays_the_original_commit_and_writes_no_second_event`
  (replay). The marker is registered in `pyproject.toml`. No new invariant logic was written —
  these are existing, real-Postgres tests, only marked.
- **JUnit/JSON evidence.** `critical_gate_evidence.build_evidence`/`write_evidence` produce a JSON
  receipt (commit, Python/Postgres versions, suite paths, pass/fail/skip counts, `ok`, message,
  coverage scopes) under `.planning/evidence/` (gitignored, uploaded as a CI artifact on every run
  via `actions/upload-artifact`, pass or fail). `critical_pg_gate.run_critical_suite` gained an
  optional `junit_out` param to persist the JUnit file instead of discarding it, and `extra_args`
  to forward pytest flags (`--import-mode=importlib`, needed once both packages' tests run
  together — same reason `task test` itself uses it).
- **Independent evidence validator.** `critical_gate_evidence.validate_evidence` re-derives
  tested-vs-skipped from the evidence's own counts rather than trusting a stored `ok` flag —
  flags zero collection, any skipped case in required mode, a missing recorded Postgres version
  in required mode, and any forbidden term (password/secret/token/credential/authorization)
  anywhere nested in the evidence, independently of what the gate itself reported.
- **Independent ledger/core coverage floors.** `task test` now runs
  `coverage report --include="packages/pulse-ledger/src/*" --fail-under=80` and the same for
  `pulse-core`, read from the same combined coverage result as the existing verdict-relay/
  schedules/identity/consent-ingress floors — no second test run.
- **Bug fixed in the same task, not a design change:** `-o markers=...` (1.1's original
  registration mechanism) *replaces* the whole `markers` ini option rather than appending to it,
  which silently un-registered every marker a real target directory's own `pyproject.toml`
  declares (`integration`, `slow`) the moment the gate ran against real per-package test dirs
  that use them — a collection error unrelated to the critical suite itself. Fixed by registering
  the marker additively via a tiny inline `pytest_configure` plugin loaded with `-p` instead.
  Covered by the existing `tests/test_critical_postgres_gate.py` (unchanged, still 14/14 green)
  and exercised for real via `task test:critical` against both real packages.
- **`tests/test_synthea_regen_workflow.py::TestMainWorkflowUntouched` relaxed.** Its previous
  assertion (`quality_runs == ["task check"]`) assumed the quality job would only ever grow one
  run step; the Postgres-provisioning step now legitimately adds a second. Rewritten to check
  what that test actually guards against — `task check` is present and `synthea:regen` never
  leaks into the quality job — rather than an exact-length equality.
- **`tests/scaffold/cat4_ci_contract.py`** gained `sudo` in `KNOWN_TOOLS` for the new
  Postgres-provisioning step.

## New Scenarios

None — the three scenarios this task owns ("Missing database prerequisite fails required mode",
"Empty or skipped critical collection fails", "Real database invariants produce evidence",
"One package cannot hide another package coverage failure", "Gate receipt distinguishes tested
from skipped") are already in `specs/critical-path-gates/spec.md`; this task provides their
evidence-surface and CI-wiring half (the other half of the first two is 1.1's fixture-level gate,
already shipped).

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/critical-path-verification/specs/`
2. Run `openspec validate critical-path-verification` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
