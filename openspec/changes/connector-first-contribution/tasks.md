# Tasks — connector-first-contribution

All implementation boxes are intentionally unchecked. Each repo-change task is a maximum
two-hour implementation slice, writes its named test first, produces one focused commit and
HANDOFF, and passes `task check`. If discovery exceeds that bound, replan before expanding it.
Live tasks are bounded attended sessions with runbook assertions and GitHub receipts, never
worktree jobs. Long loads or observation windows checkpoint between sessions.

**Entry gate:** this proposal is queued. The coordinator must first check the two active change
slots, external prerequisites in design.md, and shared-file serial lanes. `deps` lists only local
task IDs; external prerequisites are deliberate blocking conditions, not fake local task IDs.
No task is dispatched by filing or validating this proposal.

**External prerequisite for 1.2:** reviewed upstream rob-ade changes and tests for the template-owned defects from 1.1. Track them upstream and reference their PR/commit IDs; CLAUDE.md prohibits a downstream template fork. No upstream completion is asserted here.

## 1. Foundations

- [ ] 1.1 Reproduce the actual fresh-clone/check/scaffold/check/first-commit path using both generated directions and production hooks in isolated clones. Add failing controls for uninitialized OpenLore, fixed package-count assumptions and tracked timing writes. Classify each blocker as rob-ade-owned or PULSE-owned and attach exact repros.
      Tests: `tests/scaffold/test_connector_first_contribution.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Land PULSE-specific package/docs-count corrections with behavioral fixtures, then import reviewed upstream rob-ade fixes for install initialization and clean timing output through template:sync. Before this task dispatches, the upstream PRs/commits and their equivalent tests must be linked in the external-prerequisite receipt; do not patch a template fork downstream.
      Tests: `tests/scaffold/test_connector_first_contribution.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1 | serial: template synchronization and shared Taskfile/root surfaces]`

## 2. Implementation and regression evidence

- [ ] 2.1 Run both inbound and outbound first-commit journeys with hooks enabled, and document only the supported commands and prerequisites. Remove strict-xfail markers solely for proved fixes; retain the frozen audit protocol/history and all unrelated findings. Verify a green check leaves no unrelated tracked diff.
      Tests: `tests/scaffold/test_connector_first_contribution.py`.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 2]`

## 3. Integration and acceptance

- [ ] 3.1 Conduct one attended walkthrough with an engineer other than the implementer after the runbook merges. Record environment/cache/tool versions, each step, interventions and commit outcome on a GitHub tracking issue; no automated invitation, scored audit or speculative participant.
      Tests: `runbook assertions: both directions, green gate, real first commit, zero undocumented repairs`.
      `[model: sonnet | deps: 2.1 | lane: operational_discovery | wave: 3]`

- [ ] 3.2 Archive outcome evidence and update the guide through the doc-updater. If the walkthrough found an in-scope defect, reproduce and fix only that failed segment before closure; an out-of-scope defect requires a separate proposal. Add a receipt-schema fixture asserting outcome fields and absence of a numeric DX exit gate.
      Tests: `tests/test_connector_contribution_receipt.py`.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 4]`

## Plan-validation receipt

Mechanical dependency/wave checks and OpenSpec strict validation run before filing. Scenario-to-task coverage is recorded in `traceability.json` beside this file; every scenario has an owner task and every task has acceptance coverage. The plan validation test checks that mapping, dependency references and cycles. Human semantic review remains the PR review surface; no implementation acceptance is checked off here.
