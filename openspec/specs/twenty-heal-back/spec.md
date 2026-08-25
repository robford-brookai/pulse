# twenty-heal-back Specification

## Purpose
Closing D8 end to end: a rejected drag's card is written back to the state of record instead of
sitting in the wrong column, inside the ADR-0004 D17 budget the relay lag was sized for
(p99 < 30 s, "driven by the heal-back UX promise").
## Requirements
### Requirement: A rejected drag heals the card back to the state of record

On a `rejected` disposition, the webhook route SHALL trigger a projection write restoring the
card's status field to the state of record — the same state the rejection receipt names as
unchanged. The heal SHALL be attributed to the projection identity and SHALL carry only the
state value the ledger already holds.

#### Scenario: The card snaps back after an illegal drag

- **GIVEN** a card dragged to a state the catalog refuses
- **WHEN** the rejection receipt is produced
- **THEN** a heal write restores the card's status to the state of record, alongside the
  rejection note

### Requirement: A heal failure never loses the rejection

Heal-back SHALL degrade exactly as the rejection note does: a failed heal write is logged with
the card reference only, and the rejection receipt is still returned. A broken heal channel
degrades board convergence, never rejection correctness — the next applied event converges the
card regardless.

#### Scenario: A broken heal channel still rejects cleanly

- **GIVEN** a heal write that fails after its retries
- **WHEN** the rejection completes
- **THEN** the receipt is returned, the failure log carries the card reference only, and no
  retry blocks the webhook response

### Requirement: Projection writes never echo into commands

A projection or heal write to a status field fires Twenty's `patientProgram.updated` webhook
back at the route. The drag mapping SHALL classify an update whose target state equals the
state of record as a no-op disposition (`echo_of_record`) — never a command, never a rejection,
never a note — so the heal loop terminates in one bounce.

#### Scenario: A heal write's echo is a noop

- **GIVEN** a heal write that restored a card to the state of record
- **WHEN** its webhook delivery reaches the route
- **THEN** the disposition is `noop` with reason `echo_of_record`, no command is submitted, and
  no note is posted
