## Purpose

The proof that the in-pulse billing connector matches the mart it replaces: a parallel-run
window in which both compute verdicts, a per-subject comparison, and an empty-or-explained
diff as the gate the cutover cannot pass without.

## ADDED Requirements

### Requirement: Connector and mart run in parallel for a full billing month
During the reconciliation window, at least one complete billing month, the connector SHALL
declare verdicts on the live path while the mart relay continues declaring exactly as today,
and the ledger SHALL remain consistent under both writers: the pairing idempotency and
per-subject `as_of` monotonicity rules decide which declaration moves state, and the window
SHALL surface every disagreement rather than letting either writer silently win.

#### Scenario: Both writers, one consistent ledger
- **GIVEN** the connector and the mart relay both active during the window
- **WHEN** both declare verdicts for the same subject
- **THEN** every declaration is attributed to its writer, replays and stale skips are counted
  per writer, and the subject's state of record reflects the pairing rules, never an
  unexplained overwrite

### Requirement: The reconciliation sweep produces an empty-or-explained diff
A reconciliation sweep SHALL compare, per subject and verdict type, the connector's verdicts
against the mart's for the same facts, and SHALL produce a diff report in which every
disagreement is either absent or carries a written explanation (a timing artifact, a known
rule divergence with a decision record). The report SHALL carry counts and subject keys only,
never payload values or payer identifiers.

#### Scenario: A divergence is named, not averaged away
- **GIVEN** one subject where the connector says positive and the mart says negative
- **WHEN** the sweep runs
- **THEN** the report names that subject key and verdict type as a disagreement requiring
  explanation, and the window cannot close while it stands unexplained

### Requirement: Cutover is gated on the reconciliation receipt
The mart read path SHALL NOT be decommissioned until a full window's sweep reports
empty-or-explained, and the closing report SHALL be committed as the receipt on the change's
tracking record.

#### Scenario: An unexplained diff blocks the cutover
- **GIVEN** a window whose final sweep carries one unexplained disagreement
- **WHEN** cutover is proposed
- **THEN** the gate fails citing that disagreement, and the relay's mart read keeps running
