## Why

The database fixtures skip when Postgres binaries are absent, Docker integrations sit outside the ordinary gate, and inherited service coverage has explicit exclusions. A green result should say which critical invariants actually ran and fail if their mandatory prerequisites vanish.

## What Changes

- Make the critical Postgres suites mandatory in CI with explicit prerequisite and collection checks, while documenting the optional local mode.
- Run the existing credential-free LocalStack relay integration in a separate, pinned integration gate; keep live network and deploy operations out of task check.
- Publish machine-readable test counts/skips, package-specific ledger/core coverage, and a precise inherited-service exclusion inventory.
- Audit security-relevant suppressions on reachable write/consume paths; remove each proven suppression or record a bounded remediation task with ownership and an executable reproducer.

## Capabilities

### New Capabilities
- `critical-path-gates`: Mandatory real-database and transport evidence, collection/skip checks and explicit exclusion accounting.

### Modified Capabilities
None.

## Impact

Taskfile, main workflow/setup, test fixture prerequisite handling, ledger/core coverage, integration workflow, and verification docs. Serialized root-file edits. No application deployment. Rollback reverts the gate/config change; never silently converts required checks into passing skips.

## Planning status and boundaries

Proposed on 2026-09-10 at baseline `2ed0552`; implementation is not started. This is part of the
owner-requested reliability and contribution improvement plan. Review and merge of this planning
PR do not certify any runtime result. Execution keeps the two-change limit and WORKFLOW.md's
wave/serial lanes. The coordinator checks existing `reconciliation-sweeps` and
`m1-retire-patient-state` before releasing another change. No automatic dispatch, deployment,
notification, Linear sync, or cutover is part of filing this proposal. Live tasks use a GitHub
tracking issue and an attended session after their runbook PR merges; no live task is an Orca
work order. All fixtures and receipts are synthetic and contain no credentials or payload values.
