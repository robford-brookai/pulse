# Handoff Summary: critical-path-verification

Collected 4 handoff(s).

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

## critical-path-verification-task-003

### Added Requirements

None — 2.1 is covered by the existing "Transport integration is a distinct required check"
requirement.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None. Implementation matches `specs/critical-path-gates/spec.md`: a separate
`.github/workflows/transport-integration.yml` job runs the existing pinned, credential-free
LocalStack relay suite (`packages/pulse-ledger/tests/integration/test_localstack_relay.py`,
`localstack/localstack:4.6`) through a new required-mode selector
(`scripts/transport_gate.py`, `task test:transport`), bounded by both a subprocess timeout and a
job-level `timeout-minutes`, with cleanup left to the suite's own `testcontainers` teardown and
evidence uploaded as a workflow artifact. `task check`/`task test` never reach `test:transport` —
enforced by `tests/test_transport_gate_contract.py::test_transport_check_is_not_reached_from_task_check`.
"Required check activation has a receipt" is explicitly task 3.1's scope, not this one; the
workflow's header comment says so.

The task text's four verification scenarios (dropped delivery, duplicate/redrive, startup
failure, collection failure) are exercised as fixture-based subprocess cases in
`tests/test_transport_gate_contract.py`, mirroring how `test_critical_postgres_gate.py` exercises
task 1.1's scenarios — small synthetic `@pytest.mark.integration` test files run through the gate,
not a real Docker/LocalStack container, so the contract tests stay fast and credential-free.
Startup failure and collection failure reuse the same required-mode-fails-closed shape task 1.1
already established for a missing Postgres binary and zero collection. Dropped delivery and
duplicate/redrive are new to this task: a failing case must fail the gate in *both* modes (an
environment gap is forgivable, a lost delivery never is), and a passing duplicate-redelivery case
must not be flagged, since at-least-once redelivery is `relay.py`'s documented contract, not a
defect.

## New Scenarios

None beyond what's already in `specs/critical-path-gates/spec.md`.

## critical-path-verification-task-004

## Spec Updates

None. The spec's clauses for this task — the reachable-path exclusion inventory with owner and
disposition, the synthetic reproducers, and "a confirmed reachable injection or leak blocks
readiness until its focused fix merges" — were implementable as written.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

Three stale statements found in the tree while auditing. None changes the spec; all three sit in
files this task was not cleared to edit (`pyproject.toml` is in task 2.1's serial lane), so they
are recorded here rather than fixed.

1. `pyproject.toml`, the `packages/ocean/**` per-file-ignores comment, says "S608 hardcoded SQL
   (11 sites)". An isolated ruff run reports **14** `S608` sites — 10 in production code and 4 in
   ocean's own test tree. The count was correct when written and has drifted since. The comment is
   the only place the number appears; `tests/test_critical_path_debt_inventory.py` now derives it
   instead, so the fix is to drop the parenthetical rather than to update the number.
2. The same comment groups `S104 S106 S110 S310 S311 S324 S607 S608` as "security-relevant, and NOT
   style". The audit agrees with that framing for `S608` and `S106`; `S104` (two container bind
   addresses under `__main__`) and `S311` (eight jitter/simulation draws) are not security-relevant
   in their current sites, and keeping them in the same sentence as `S608` makes the group read as
   more alarming than it is. Proposed for whoever next touches that block: split the comment into
   the injection/credential rules and the operational-posture rules.
3. `design/migration/ocean-to-pulse-adaptation-plan.md` and ADR-0002 both describe "sixteen
   services" as a single population. For reachability they are not one population: fifteen of the
   sixteen publish to or consume from the bus, and exactly one (`stacte-bridge`) does neither. That
   distinction carries most of this task's dispositions, and it is now pinned by a test rather than
   left as prose.

## New Scenarios

None proposed. The two scenarios this task owns — "Reachable security suppression is accounted
for" and the coverage clause's companion — are covered as written by
`tests/test_critical_path_debt_inventory.py`.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/critical-path-verification/specs/`
2. Run `openspec validate critical-path-verification` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
