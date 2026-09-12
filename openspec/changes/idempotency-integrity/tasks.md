# Tasks — idempotency-integrity

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

- [x] 1.1 Define canonical request v1 and authenticated writer binding at the API boundary; produce golden vectors for UTC aliases, key order, list order, payload/evidence changes, batch and webhook principals. Write the proposed D16 amendment ADR and a compatibility inventory template alongside the tests.
      Tests: `packages/pulse-ledger/tests/test_request_fingerprint.py`.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`

- [x] 1.2 Add the companion binding-table migration, event/key foreign keys, restrictive service grants and version fields; test upgrade from populated pre-binding schema, rollback preservation and atomic binding insertion failure.
      Tests: `packages/pulse-ledger/tests/test_idempotency_binding_migration.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1 | serial: ledger Alembic migration chain and schema grants]`

## 2. Implementation and regression evidence

- [x] 2.1 Implement exact-match replay and collision rejection in the commit path, including a race loser that must compare bindings before returning. Test same/different writer and same/different fingerprint races, no writes on conflict, and original result stability after reversal and same-timestamp/later-start transactions.
      Tests: `packages/pulse-ledger/tests/test_idempotency_binding.py`.
      `[model: opus | deps: 1.2 | lane: repo_change | wave: 2]`

- [x] 2.2 Implement legacy ownership/fingerprint reconstruction from proved event fields; bind verified legacy rows transactionally and reject unverifiable ones with the distinct generic reason. No key deletion or guessed values. Record the non-enforcement inventory that must clear before rollout.
      Tests: `packages/pulse-ledger/tests/test_legacy_idempotency_binding.py`.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 3]`

## 3. Integration and acceptance

- [x] 3.1 Wire 409 idempotency_conflict into single commands and per-item batch results, and 200 rejected disposition into Twenty. Add the non-transient SDK classification and tests proving no prior event/result or sensitive value escapes on a cross-writer conflict.
      Tests: `packages/pulse-ledger/tests/test_api_idempotency_conflict.py`.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 4]`

- [x] 3.2 Add SDK/connector/webhook compatibility cases for valid existing retries, legacy-unverifiable handling, rollout preflight and safe receipt redaction. Update command/SDK migration guidance and the D16 ADR through the doc-updater; prepare the attended rollout runbook.
      Tests: `packages/pulse-core/tests/test_idempotency_conflict_contract.py`.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 5]`

## 4. Attended validation

- [ ] 4.1 Attend a synthetic dev compatibility rehearsal after the runbook PR merges and the D16 amendment/legacy inventory gates clear. Verify an old producer exact retry, a conflict, a webhook retry and the retained original event count; attach versioned receipts to a GitHub tracking issue. This is not production enforcement.
      Tests: `runbook assertions: exact retry same event; conflicts write zero rows; no result disclosure`.
      `[model: sonnet | deps: 3.2 | lane: operational_discovery | wave: 6]`

## Plan-validation receipt

Mechanical dependency/wave checks and OpenSpec strict validation run before filing. Scenario-to-task coverage is recorded in `traceability.json` beside this file; every scenario has an owner task and every task has acceptance coverage. The plan validation test checks that mapping, dependency references and cycles. Human semantic review remains the PR review surface; no implementation acceptance is checked off here.
