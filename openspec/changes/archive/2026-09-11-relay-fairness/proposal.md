## Why

The current relay limits a subject-sorted row query before testing backoff and subject locks. A large backlog for an early subject can consume the selection budget and delay unrelated ready subjects; the review identified a reproducible-risk hypothesis, not a measured production outage.

## What Changes

- Select ready subject heads fairly, bound work per subject, and retain a resumable scan position between passes so busy, locked, and backing-off subjects cannot monopolize selection.
- Re-read pending rows after obtaining the existing per-subject lock; retain transaction/outbox atomicity, event-id dedupe, five-attempt dead-lettering, and manual redrive.
- Make the transport boundary explicit: relay publication order is distinct from subscriber arrival order; exercise reordered/duplicated input at existing projection consumers.
- Add deterministic starvation, lock-contention, ambiguous-publish, restart, and poison-row regression cases plus a synthetic load receipt.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `ledger-distribution`: Add fair service of independent subjects and precisely scoped publication-order guarantees.

## Impact

`pulse_ledger.relay`, relay_worker, relay tests, the ledger-distribution delta, and the relay runbook. No new producer, command, bus, or ledger event schema. Roll back the relay binary while retaining journal/outbox rows; reset only ephemeral scheduling state.

## Planning status and boundaries

Proposed on 2026-09-10 at baseline `2ed0552`; implementation is not started. This is part of the
owner-requested reliability and contribution improvement plan. Review and merge of this planning
PR do not certify any runtime result. Execution keeps the two-change limit and WORKFLOW.md's
wave/serial lanes. The coordinator checks existing `reconciliation-sweeps` and
`m1-retire-patient-state` before releasing another change. No automatic dispatch, deployment,
notification, Linear sync, or cutover is part of filing this proposal. Live tasks use a GitHub
tracking issue and an attended session after their runbook PR merges; no live task is an Orca
work order. All fixtures and receipts are synthetic and contain no credentials or payload values.
