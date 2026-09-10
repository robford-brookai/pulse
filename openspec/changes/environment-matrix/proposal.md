## Why

The existing environment-matrix seed describes staging and artifact promotion, but dev service definitions remain tenant-specific and ledger:deploy only pushes a bare image name. Repeatable release identity, staging evidence and a working rollback path are prerequisites to a credible readiness assessment.

## What Changes

- Turn the existing seed into a held proposal: define environment configuration, target validation and credential references without allocating live infrastructure.
- Build and promote a release manifest containing immutable image digests, catalog version, migration head, Twenty artifact checksum and Synthea manifest identity.
- Repair the registry/rollout path, parameterize current Duplo definitions, and verify deployed image and migration identities; keep D14 runtime selection as a prerequisite rather than silently replacing it.
- Consume a verified successful Synthea artifact, seed synthetic staging, and run round-trip, heal-back, freshness and rebuild/rollback checks before promotion.
- Keep production activation and the billing cutover decision outside this change; supply their reproducible artifact and evidence inputs.

## Capabilities

### New Capabilities
- `environment-promotion`: Target isolation, release identity, verified synthetic staging and promotion/rollback evidence.

### Modified Capabilities
None.

## Impact

Seed/roadmap status, deploy scripts and Taskfile, Duplo service templates, staging loader, release manifest schema and runbooks. Serial root-file edits. No live resources created by this PR. Application rollback promotes the previous manifest; irreversible database changes require a forward repair and never an automatic downgrade.

## Planning status and boundaries

Proposed on 2026-09-10 at baseline `2ed0552`; implementation is not started. This is part of the
owner-requested reliability and contribution improvement plan. Review and merge of this planning
PR do not certify any runtime result. Execution keeps the two-change limit and WORKFLOW.md's
wave/serial lanes. The coordinator checks existing `reconciliation-sweeps` and
`m1-retire-patient-state` before releasing another change. No automatic dispatch, deployment,
notification, Linear sync, or cutover is part of filing this proposal. Live tasks use a GitHub
tracking issue and an attended session after their runbook PR merges; no live task is an Orca
work order. All fixtures and receipts are synthetic and contain no credentials or payload values.
