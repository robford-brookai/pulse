## Purpose

Defines what downstream services read from the ledger itself: current-state enumeration that never
depends on projection freshness, identity candidate lookup, durable writer cursors, and the
quarantine review queue.

## ADDED Requirements

### Requirement: Current state is readable from the ledger

The ledger SHALL expose a current-state read API sufficient to enumerate subjects by type and
state — including active and on-hold Enrollments for month-open — reading the co-committed state
rows, not a projection (so clock-driven jobs never depend on projection freshness).

#### Scenario: Month-open enumerates from the ledger

- **GIVEN** enrollments in `active`, `on_hold`, and `ended`
- **WHEN** the read API is asked for enrollments in `active` or `on_hold`
- **THEN** exactly the active and on-hold enrollments are returned, consistent with the ledger's
  own state rows at read time

### Requirement: Identity candidates are queryable

The read API SHALL support identity resolution lookups: exact match on ExternalIdentifier
`(system, value)`, and candidate retrieval by the normalized composite used by the deterministic
matcher. Uniqueness of `(system, value)` SHALL be enforced at resolution time.

#### Scenario: Exact identifier match returns one person

- **GIVEN** a person holding ExternalIdentifier `(system S, value V)`
- **WHEN** a lookup for `(S, V)` runs
- **THEN** exactly that person is returned

#### Scenario: Attaching a duplicate identifier is rejected

- **GIVEN** `(S, V)` already attached to person A
- **WHEN** `attach_identifier` is declared binding `(S, V)` to person B
- **THEN** the command is rejected and the conflict names person A

### Requirement: Writers have durable cursors

The ledger SHALL provide a writer-state facility keyed by writer id: a writer SHALL be able to
persist and read back a cursor so a crashed run resumes without re-reading or re-declaring
completed work.

#### Scenario: Crash and resume

- **GIVEN** a writer that persisted cursor C after batch N
- **WHEN** the writer restarts and reads its cursor
- **THEN** it receives C and continues from batch N+1, and idempotency makes any overlap a replay

### Requirement: Ambiguous resolutions land in a review queue

The ledger schema SHALL include a quarantine review queue: a subject held with a
`resolution_hold` fact SHALL appear as a pending row, countable while pending, and SHALL leave the
queue only by a declared resolution from the reviewer role.

#### Scenario: Quarantine is countable and drains by declaration

- **GIVEN** a referral quarantined with a `resolution_hold` fact
- **WHEN** the review queue is read
- **THEN** the referral appears as pending with its candidate set, and after a reviewer declares
  the resolution it no longer appears
