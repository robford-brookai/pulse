## Why

A reused key currently returns the stored event even when the new declaration differs; tests deliberately encode that behavior. The server must distinguish an exact retry from a producer collision and must not return another authenticated writer's result merely because that writer supplied the same key.

## What Changes

- Bind a key to the authenticated writer and a versioned canonical fingerprint of the accepted request; check that binding before returning any stored result.
- **BREAKING for mismatched-key reuse:** return a stable conflict rejection instead of a successful replay; retain all valid existing retry behavior and the existing wire key format.
- Use the same integrity check for single, batch, and signed Twenty ingress; preserve the webhook disposition contract rather than creating retry storms.
- Add an additive migration and explicit legacy-key compatibility path; verify races, rollback, and retries of events later corrected or reversed.
- Document the behavior change and consumer migration in a new ADR that amends D16, plus SDK classification and connector compatibility tests.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `command-api`: Bind replay to authenticated writer and canonical request; reject mismatched reuse without a second event or result disclosure.

## Impact

Ledger idempotency storage/commit logic, api/api_server, pulse-core receipt classification, Twenty mapping, migration tests, and D16 amendment. No new producer or writer credential. Rollback uses an application rollback with the additive binding records retained; do not drop keys or disable mismatch checks as a workaround.

## Planning status and boundaries

Proposed on 2026-09-10 at baseline `2ed0552`; implementation is not started. This is part of the
owner-requested reliability and contribution improvement plan. Review and merge of this planning
PR do not certify any runtime result. Execution keeps the two-change limit and WORKFLOW.md's
wave/serial lanes. The coordinator checks existing `reconciliation-sweeps` and
`m1-retire-patient-state` before releasing another change. No automatic dispatch, deployment,
notification, Linear sync, or cutover is part of filing this proposal. Live tasks use a GitHub
tracking issue and an attended session after their runbook PR merges; no live task is an Orca
work order. All fixtures and receipts are synthetic and contain no credentials or payload values.
