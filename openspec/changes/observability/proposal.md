## Why

Health and readiness probes now exist, but a committed probe is not evidence of deployed failure detection, alert delivery or recovery. The queued Datadog work needs a bounded implementation plan that closes these operational gaps and consumes the existing reconciliation receipts.

## What Changes

- Implement the three existing runtime-readiness SLOs and the launch monitor set with project:pulse and per-service tags, runbook links and explicit no-data handling.
- Reuse shipped warehouse-sync liveness/token-expiry behavior; add synthetic fault drills proving detection, backlog retention, recovery and reconciliation.
- Separate monitor definitions from live activation and routing; verify destinations in the attended setup without inventing an on-call owner.
- Collect versioned evidence for service restart, temporary database failure, transport backlog and consumer token expiry; retain links to existing rebuild/reconciliation work.

## Capabilities

### New Capabilities
- `runtime-observability`: SLO/monitor definitions, safe signal contracts, routing and failure/recovery evidence.

### Modified Capabilities
None.

## Impact

Existing telemetry emitters, Datadog IaC/config, runbooks, monitor fixtures, and an attended recovery drill. No new SLO, no replacement health framework, no new ledger writer. Rollback disables only the new monitor configuration, restores the previous version and records the monitoring gap.

## Planning status and boundaries

Proposed on 2026-09-10 at baseline `2ed0552`; implementation is not started. This is part of the
owner-requested reliability and contribution improvement plan. Review and merge of this planning
PR do not certify any runtime result. Execution keeps the two-change limit and WORKFLOW.md's
wave/serial lanes. The coordinator checks existing `reconciliation-sweeps` and
`m1-retire-patient-state` before releasing another change. No automatic dispatch, deployment,
notification, Linear sync, or cutover is part of filing this proposal. Live tasks use a GitHub
tracking issue and an attended session after their runbook PR merges; no live task is an Orca
work order. All fixtures and receipts are synthetic and contain no credentials or payload values.
