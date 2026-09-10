# Tasks — observability

All implementation boxes are intentionally unchecked. Each repo-change task is a maximum
two-hour implementation slice, writes its named test first, produces one focused commit and
HANDOFF, and passes `task check`. If discovery exceeds that bound, replan before expanding it.
Live tasks are bounded attended sessions with runbook assertions and GitHub receipts, never
worktree jobs. Long loads or observation windows checkpoint between sessions.

**Entry gate:** this proposal is queued. The coordinator must first check the two active change
slots, external prerequisites in design.md, and shared-file serial lanes. `deps` lists only local
task IDs; external prerequisites are deliberate blocking conditions, not fake local task IDs.
No task is dispatched by filing or validating this proposal.

**External prerequisites for 3.1–3.2:** merged runbooks, verified test environment/release identity, confirmed owner-role and notification destination. Existing reconciliation-sweeps 4.1 remains owned by that change. No production recipient or paging activation is assumed.

## 1. Foundations

- [ ] 1.1 Define safe telemetry field schema and SLO numerator/denominator/window semantics using the three existing targets. Add fixtures for absent/stale telemetry versus idle traffic and for end-to-end correlation without credentials, raw exceptions or payload values.
      Tests: `tests/test_runtime_telemetry_contract.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`

- [ ] 1.2 Implement/test API availability and commit-latency monitor/SLO definitions with service/project/env tags, threshold windows and runbook links. Validate fixture histories for healthy, failing and no-data states.
      Tests: `tests/test_api_monitor_definitions.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 1.3 Implement/test outbox lag/DLQ and projection-freshness monitor definitions. Distinguish oldest-pending age from latency distributions, and alert-at-depth-one from page-after-15-minutes. Use per-consumer fixture histories.
      Tests: `tests/test_projection_monitor_definitions.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 1.4 Implement/test verdict >26h staleness, missed month-open, reconciliation drift and quarantine depth/age monitors. Reference existing sweep receipts and runbooks; define no-data/disabled-consumer states and routing rules without naming unverified recipients.
      Tests: `tests/test_scheduled_monitor_definitions.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 2. Implementation and regression evidence

- [ ] 2.1 Build a bounded synthetic fault harness and receipt validator for stopped/wedged consumer, token expiry, dependency outage and outbox backlog. Reuse shipped health handlers and reconciliation core. Test cleanup, abort limits, queue retention, resumed progress and redaction offline; write attended runbooks and verified-destination preflight.
      Tests: `tests/test_runtime_recovery_drill.py`.
      `[model: sonnet | deps: 1.2, 1.3, 1.4 | lane: repo_change | wave: 2]`

## 3. Integration and acceptance

- [ ] 3.1 In an attended isolated dev/staging session, verify image/probe identity and owner/destination, activate only the test monitor and exercise stopped-consumer/token-expiry recovery without revoking a shared credential. Attach detection, notification and backlog/conformance receipts to a GitHub tracking issue.
      Tests: `runbook assertions: configured detection window, no early ack, restart/resume and agreement after recovery`.
      `[model: sonnet | deps: 2.1 | lane: operational_discovery | wave: 3]`

- [ ] 3.2 In a separate bounded attended session, exercise temporary dependency failure and outbox backlog, validate monitor recovery and cleanup, and link the existing reconciliation/rebuild receipts. Record any unfilled production paging owner as a remaining activation gate; do not activate production here.
      Tests: `runbook assertions: abort isolation, delivery retained, no duplicates in projection, signal recovery and cleanup`.
      `[model: sonnet | deps: 3.1 | lane: operational_discovery | wave: 4]`

## Plan-validation receipt

Mechanical dependency/wave checks and OpenSpec strict validation run before filing. Scenario-to-task coverage is recorded in `traceability.json` beside this file; every scenario has an owner task and every task has acceptance coverage. The plan validation test checks that mapping, dependency references and cycles. Human semantic review remains the PR review surface; no implementation acceptance is checked off here.
