# Tasks — company-readiness

Queued; maximum two hours per task, tests first, one focused commit and HANDOFF. Replan larger findings. Respect the two-active-change limit. No live task runs unattended; its reviewed runbook must merge first. No specs are required because this change only documents and verifies existing behavior.

## 1. Reviewable preparation

- [ ] 1.1 Refresh README status/navigation and project-specific CLAUDE context from code and existing receipts; test that documented entry paths and status evidence links resolve. Preserve template-owned conventions.
      Tests: `tests/test_company_entry_links.py`.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0 | serial: shared README and project guidance]`

- [ ] 1.2 Publish the documentation authority map, contradiction inventory and ownership/escalation table; mark unknown owners explicitly and route spec labels through the doc-updater. Test unresolved ownership cannot be represented as operationally ready.
      Tests: `tests/test_readiness_ownership.py`.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

- [ ] 1.3 Write the read-only sharing-review runbook and receipt validator, covering audience, accessible refs/history, scan coverage, restricted findings and unavailable permission checks. Test partial coverage is incomplete rather than pass.
      Tests: `tests/test_sharing_review_receipt.py`.
      `[model: sonnet | deps: 1.2 | lane: repo_change | wave: 2]`

## 2. Evidence and release preparation

- [ ] 2.1 Conduct the attended sharing review after its runbook merges and record the redacted receipt on a GitHub issue. Do not alter permissions, rewrite history or send announcements.
      Tests: `runbook assertions: coverage recorded, findings redacted, unknown checks incomplete`.
      `[model: sonnet | deps: 1.3 | lane: operational_discovery | wave: 3]`

- [ ] 2.2 Incorporate the verified fresh-checkout and first-contribution receipt owned by connector-first-contribution in PR #452; record exact code/tool versions and expected demo results. External gate: that receipt must exist before dispatch. Test missing or failed evidence cannot pass readiness.
      Tests: `tests/test_onboarding_readiness_receipt.py`.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 4]`

- [ ] 2.3 Publish separate company-visibility and demo-readiness outcomes with outstanding findings and owners. Demo readiness consumes engineering-demo acceptance and remains incomplete until available; publication does not announce or change visibility. Test these outcomes independently with synthetic pass/fail/incomplete fixtures.
      Tests: `tests/test_company_readiness_outcomes.py`.
      `[model: sonnet | deps: 2.2 | lane: repo_change | wave: 5]`
