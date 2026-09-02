## Purpose

The shared primitives every pulse connector stands on — the inbound read contract, the declare
pipeline, the outbound consume loop, and the credential posture — extracted into `pulse-core`
from the three integrations that already work, so the next connector is configuration and
mapping, not re-implementation.

## ADDED Requirements

### Requirement: The kit is extracted, not invented

The connector kit's primitives SHALL be extracted from the existing integrations
(consent-ingress, verdict-relay, twenty-projection), and those packages SHALL be refactored
onto the kit in the same change that introduces it — the kit has no behavior that is not
already proven by a shipped integration, and no shipped integration keeps a private copy of a
primitive the kit provides.

#### Scenario: Existing integrations run on the kit

- **GIVEN** the kit landed and the three integrations refactored onto it
- **WHEN** demos 1 through 4 run
- **THEN** every assertion passes unchanged — the refactor is behavior-preserving

### Requirement: Inbound reads follow the row-source and cursor contract

The kit SHALL provide the inbound read contract: a row source yielding validated rows, per-row
validation that fails naming the offending row and column (never a contact or payload value),
and a durable cursor persisted through the ledger's writer-state facility scoped to the
connector's own writer id, so a crashed run resumes without loss or double-processing.

#### Scenario: A malformed row is named, the run survives

- **GIVEN** a page containing one row missing a contract column
- **WHEN** the connector reads it
- **THEN** the row is counted as an error naming its position and column, no payload value is
  logged, and the remaining rows process normally

#### Scenario: A crashed run resumes from the durable cursor

- **GIVEN** a run that persisted its cursor and then died mid-batch
- **WHEN** the next run starts
- **THEN** it resumes from the persisted cursor, and rows already declared classify as replays

### Requirement: Declares go through the shared pipeline

The kit SHALL provide the declare pipeline: client-side idempotency-key derivation (D16),
response classification (committed | replayed | rejected | transient) with retry on transient
only, and a counted receipt emitted at end of run — the operator-visible contract for every
connector run.

#### Scenario: A rerun declares nothing twice

- **GIVEN** a batch fully declared by a prior run
- **WHEN** the same batch is processed again
- **THEN** every submission classifies as replayed, no new event exists, and the receipt
  counts the replays

### Requirement: Outbound consumption follows the consume-loop contract

The kit SHALL provide the outbound consume loop: an EventBridge rule + SQS queue per
connector, event-id dedupe, delete-after-success, and a monotonic per-record watermark for
write-backs into the target system — the twenty-projection pattern generalized.

#### Scenario: A redelivered event applies once

- **GIVEN** a committed event delivered twice by the queue
- **WHEN** the consume loop processes both deliveries
- **THEN** the write-back applies exactly once and the second delivery is deleted as a dedupe
  hit

### Requirement: One connector, one credential, no ledger internals

Each connector SHALL hold exactly one writer credential of its own (actor derived from the
credential, never from payload — D15) plus the target system's credential for write-backs,
and SHALL never hold a ledger database connection: writes go through the command API, reads
through the bus. Credential names live in configuration, values in the environment, and no
credential value SHALL appear in any log, receipt, or error message.

#### Scenario: A connector cannot write ledger tables

- **GIVEN** any connector built on the kit
- **WHEN** its runtime configuration is inspected
- **THEN** it carries no ledger DSN — its only pulse-facing surfaces are the command API and
  its own queue
