## Purpose

Define verifiable source extraction guarantees so every Pulse connector can hydrate, resume, and reconcile without silent data loss or fabricated history.

## ADDED Requirements

### Requirement: Verified capability manifest

Each source adapter SHALL publish a versioned manifest identifying the source owner, extraction mode, API/schema and mapping versions, identity namespace, capabilities, limits, evidence references, and unsupported guarantees. Unverified mandatory guarantees SHALL prevent readiness.

#### Scenario: Unknown capabilities prevent readiness

- **GIVEN** a manifest with unverified deletion and history coverage
- **WHEN** readiness is evaluated
- **THEN** the missing guarantees are reported with an owner and the affected ingestion mode remains blocked

### Requirement: Identity lifecycle

The adapter SHALL declare immutable source identity and namespace, identifier reuse/incarnation rules, merge and deletion semantics, and crosswalk resolution. Ambiguous identities SHALL enter a durable hold without guessing a subject.

#### Scenario: Reused identifiers cannot merge subjects

- **GIVEN** an identifier reused for a different source incarnation
- **WHEN** both observations are mapped
- **THEN** they remain distinguishable and unresolved crosswalks are held

### Requirement: Consistent paginated extraction

A paginated adapter SHALL specify deterministic total ordering with a unique tie-breaker, snapshot or bounded-window semantics, page size limits, and token expiration recovery. Concurrent mutations SHALL not silently omit rows; an interface without an adequate consistency guarantee SHALL fail readiness.

#### Scenario: Mutating pages and expired tokens recover completely

- **GIVEN** a bounded extraction with equal timestamps, a concurrent edit, and an expired page token
- **WHEN** the adapter resumes using its declared recovery procedure
- **THEN** every eligible observation is accounted for and repeated observations retain their original command identity

### Requirement: Mode-specific change capture

The manifest SHALL choose polling, CDC, or push and specify ordered source version/position, lateness policy, deletions or tombstones, retention, and gap recovery. Polling SHALL specify watermarks and overlap; CDC SHALL specify resume-token validity; push SHALL specify authentication, deduplication and acknowledgement durability. No source SHALL be required to provide all three modes.

#### Scenario: Lost change position stops rather than skips

- **GIVEN** a change position outside the declared retention window
- **WHEN** the adapter attempts incremental extraction
- **THEN** it reports a gap, stops advancement, and invokes a bounded recovery procedure including deletion accounting

### Requirement: Snapshot and live overlap

Batch and incremental adapters SHALL define a common observation identity or explicit boundary reconciliation that prevents duplicate declarations at handover. A historical row without CDC position SHALL not be assigned an invented log position. Mapping changes SHALL not silently reinterpret a previously committed command identity.

#### Scenario: Snapshot overlap declares a fact once

- **GIVEN** the same fact appears in a historical snapshot without a log position and in the live stream
- **WHEN** the batch hands over at its recorded boundary
- **THEN** the fact is declared once or held for boundary reconciliation, with no fabricated position

### Requirement: Historical evidence and time

Each declaration SHALL retain protected source provenance, evidence class, extraction time, mapping version and known effective time while Pulse assigns recorded time. Missing history, unknown timestamps and current-state-only evidence SHALL be explicit; inferred history SHALL not be represented as observed transitions.

#### Scenario: Missing history remains visible

- **GIVEN** a source exposes only current state and no reliable transition timestamp
- **WHEN** a historical extraction is requested
- **THEN** the receipt reports unavailable history and the adapter does not fabricate a transition sequence or effective timestamp

### Requirement: Bounded source load

The adapter SHALL declare and enforce request and concurrency budgets, bounded timeouts, rate-limit handling, retry budgets and backpressure. It SHALL stop fetching when durable downstream capacity is exhausted and expose safe operational counters.

#### Scenario: Rate limits and backlog bound extraction

- **GIVEN** a source returns a rate limit while downstream capacity is exhausted
- **WHEN** the next extraction cycle runs
- **THEN** the adapter respects the retry delay and configured budgets and performs no unbounded buffering or additional fetches

### Requirement: Schema and mapping evolution

The adapter SHALL pin source and mapping versions, validate required fields and types, and distinguish compatible additions from breaking changes. Breaking changes SHALL halt or durably quarantine affected observations before checkpoint advancement; an explicit migration and replay policy SHALL precede resumption.

#### Scenario: Breaking source changes preserve the recovery point

- **GIVEN** a required source field changes type
- **WHEN** validation runs
- **THEN** the affected observation is safely quarantined or the run stops, and a versioned repair is required before resumption

### Requirement: Acknowledgements and protected recovery

The adapter SHALL use least-privilege source credentials and its own Pulse writer credential, hold no ledger DSN, and persist checkpoints only after every prior observation has a durable accepted/replayed result or protected recoverable hold. Unknown commit outcomes SHALL retry the identical command identity. Logs and general receipts SHALL contain no secrets or PHI; payload-bearing holds and DLQs SHALL remain access-controlled in the approved data boundary with retention and replay ownership.

#### Scenario: Lost acknowledgement and secret-bearing errors recover safely

- **GIVEN** a command commits but its acknowledgement is lost and a source error includes protected data
- **WHEN** the adapter restarts
- **THEN** it retries the same command identity without advancing past uncertainty and emits only redacted operational metadata

### Requirement: Reconciliation and ownership

Each adapter SHALL supply measurable source-to-ledger completeness accounting by bounded window, mutually exclusive observation outcomes, explicit lag and discrepancy thresholds, and an owned runbook for holds, recovery and escalation. Pulse SHALL own pull extraction, mapping and command submission; source engineering SHALL own missing interface guarantees. Demo state/history API reads SHALL use a separate client and credential without broadening connector access.

#### Scenario: Unaccounted rows fail the acceptance receipt

- **GIVEN** a source window contains an observation absent from all accepted, replayed, held, rejected or explicitly excluded outcomes
- **WHEN** the acceptance check and ownership review run
- **THEN** the receipt fails with a discrepancy count and owner, and the demo reader remains separate from the connector writer
