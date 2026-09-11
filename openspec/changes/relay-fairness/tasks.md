# Tasks — relay-fairness

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

- [x] 1.1 Introduce the candidate-subject scan and explicit reusable scheduling state. First reproduce a subject filling the old LIMIT; advance across backed-off and locked subjects and wrap at end. Assert finite-set scan-cycle progress with bounded examination.
      Tests: `packages/pulse-ledger/tests/test_relay_fairness.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Wire fair selection into relay_worker with a per-subject row budget. Acquire the subject lock before rereading its pending head; test that an old pre-lock snapshot is never treated as current after another relay publishes.
      Tests: `packages/pulse-ledger/tests/test_relay_fairness.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 2. Implementation and regression evidence

- [ ] 2.1 Preserve retry/DLQ/manual-redrive semantics and prove two concurrent relays, ambiguous publishes, worker restart, continuous hot-subject traffic and a backoff head. Use two real Postgres connections and controlled scheduling, not sleep-based race tests.
      Tests: `packages/pulse-ledger/tests/test_relay_fairness_concurrency.py`.
      `[model: opus | deps: 1.2 | lane: repo_change | wave: 2]`

- [ ] 2.2 Exercise duplicated, reordered and late-redriven events at existing projection boundaries; retain watermark/dedupe invariants and document the publication-versus-arrival ordering boundary through the doc-updater. Any consumer failing its current contract gets a reproducer and focused replan before closure.
      Tests: `packages/twenty-projection/tests/test_relay_delivery_contract.py`.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 3]`

## 3. Integration and acceptance

- [ ] 3.1 Add a synthetic skewed-backlog benchmark command and bounded integration fixture; record query plan, budgets, backlog drain and two-relay progress against the baseline. Update the relay runbook and propose D17 wording clarification via HANDOFF; no live deployment in this task.
      Tests: `packages/pulse-ledger/tests/integration/test_relay_fairness_load.py`.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 4]`

## Plan-validation receipt

Mechanical dependency/wave checks and OpenSpec strict validation run before filing. Scenario-to-task coverage is recorded in `traceability.json` beside this file; every scenario has an owner task and every task has acceptance coverage. The plan validation test checks that mapping, dependency references and cycles. Human semantic review remains the PR review surface; no implementation acceptance is checked off here.
