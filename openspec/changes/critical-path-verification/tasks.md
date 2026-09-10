# Tasks — critical-path-verification

All implementation boxes are intentionally unchecked. Each repo-change task is a maximum
two-hour implementation slice, writes its named test first, produces one focused commit and
HANDOFF, and passes `task check`. If discovery exceeds that bound, replan before expanding it.
Live tasks are bounded attended sessions with runbook assertions and GitHub receipts, never
worktree jobs. Long loads or observation windows checkpoint between sessions.

**Entry gate:** this proposal is queued. The coordinator must first check the two active change
slots, external prerequisites in design.md, and shared-file serial lanes. `deps` lists only local
task IDs; external prerequisites are deliberate blocking conditions, not fake local task IDs.
No task is dispatched by filing or validating this proposal.

## 1. Foundations

- [ ] 1.1 Add required-Postgres fixture mode and a critical-suite selector. Fail required mode on missing binaries, zero collection or skipped mandatory cases; preserve explicit local optional mode. Cover these failure paths in subprocess fixtures, not YAML-only checks.
      Tests: `tests/test_critical_postgres_gate.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Provision/pin the database prerequisite in CI; run required mode through the existing quality contract. Emit JUnit/JSON suite and tool-version evidence and ledger/core independent coverage floors from the same coverage result. Check collection/skip summaries in the evidence validator.
      Tests: `tests/test_critical_gate_evidence.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1 | serial: Taskfile.yml, pyproject.toml and main CI setup are shared roots]`

## 2. Implementation and regression evidence

- [ ] 2.1 Wire the existing LocalStack relay integration to an explicit pinned, bounded, credential-free workflow and target, including cleanup and artifacts. Verify a dropped delivery, duplicate/redrive case, startup failure and collection failure; keep live targets out of task check.
      Tests: `tests/test_transport_gate_contract.py`.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 2 | serial: Taskfile.yml and integration workflow wiring]`

- [ ] 2.2 Audit reachable PULSE write/consume paths against the inherited typing/coverage/security-suppression exclusions. Add synthetic redaction/query-boundary regression cases and a path→owner-role→risk→disposition inventory. File focused repro-backed fixes for confirmed defects; unresolved reachable defects block readiness.
      Tests: `tests/test_critical_path_debt_inventory.py`.
      `[model: opus | deps: 1.2 | lane: repo_change | wave: 2]`

## 3. Integration and acceptance

- [ ] 3.1 Verify the new checks ran on the same commit and configure/verify required-check rules only in an attended repository-administration session after a tested runbook PR. Capture missing-prerequisite failure evidence, successful invariant counts and ruleset check identities on a GitHub tracking issue.
      Tests: `runbook assertions: mandatory suites ran, no required skips, required checks match actual workflow names`.
      `[model: sonnet | deps: 2.1, 2.2 | lane: operational_discovery | wave: 3]`

## Plan-validation receipt

Mechanical dependency/wave checks and OpenSpec strict validation run before filing. Scenario-to-task coverage is recorded in `traceability.json` beside this file; every scenario has an owner task and every task has acceptance coverage. The plan validation test checks that mapping, dependency references and cycles. Human semantic review remains the PR review surface; no implementation acceptance is checked off here.
