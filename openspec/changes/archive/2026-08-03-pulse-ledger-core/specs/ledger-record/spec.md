## Purpose

Defines the record itself: the append-only, bitemporal event ledger with current state
co-committed per subject, correction by reversal, evidence classes for backfilled history, and a
shape that lands flat in the warehouse for independent re-derivation.

## ADDED Requirements

### Requirement: Events are append-only and corrected by reversal

The ledger SHALL be append-only. An event row, once committed, SHALL never be updated or deleted.
A mistake SHALL be corrected by committing a reversal event that references the event it voids
(I7). The warehouse immutability detector (`Q_EVENT_MUTATIONS`) SHALL find zero mutated rows.

#### Scenario: A committed event cannot be changed

- **GIVEN** a committed event
- **WHEN** any writer attempts to update or delete its row
- **THEN** the store rejects the mutation and the event remains byte-identical

#### Scenario: Correction produces a reversal, not an edit

- **GIVEN** an event committed in error
- **WHEN** the correction is declared
- **THEN** a new reversal event referencing the voided event's id is appended, and both events
  remain readable in history

### Requirement: Every event is bitemporal

Every event SHALL carry `effective_at` (when the fact was true in the world) and `recorded_at`
(when the ledger learned it, set by the server, never by the client). No consumer contract SHALL
present `recorded_at` as occurrence time (I10).

#### Scenario: Forward declaration

- **WHEN** a writer declares a transition that just happened
- **THEN** the committed event has `effective_at` supplied by the writer and `recorded_at` set by
  the server, and the two are within normal clock skew

#### Scenario: Backdated declaration

- **WHEN** a writer declares a fact with `effective_at` in the past
- **THEN** the event commits with the past `effective_at` and a current `recorded_at`, and
  current-state folds order by `effective_at`

### Requirement: Current state is co-committed with each event

Each subject (Referral, Consent, Enrollment, BillingEpisode, Device, Contract grains per object
model v0.7) SHALL have exactly one current-state row, updated in the same transaction as the event
that changes it. State SHALL never be reconstructed at read time by consumers (I3).

#### Scenario: Event and state commit atomically

- **WHEN** a legal transition commits
- **THEN** the event row and the subject's current-state row are visible together, and no reader
  can observe the event without the updated state or vice versa

#### Scenario: Failed command leaves no partial write

- **WHEN** a command fails after validation for any reason
- **THEN** neither an event row nor a state change is visible

### Requirement: Events carry evidence class and epoch

Every event SHALL carry an evidence class (`E0` direct, `E1` corroborated, `E2` single-source
inferred, `E3` interpolated with interval bounds, `E4` genesis) and SHALL be attributable to an
epoch (declared forward vs reconstructed backfill), so backfilled history is distinguishable
without a schema migration. Forward declarations default to `E0`.

#### Scenario: Forward events default to direct evidence

- **WHEN** a forward writer declares a transition without an evidence class
- **THEN** the event commits with evidence class `E0` and the declared epoch

#### Scenario: Interpolated backfill carries its bounds

- **WHEN** a backfill writer commits an `E3` event
- **THEN** the event records the interpolation interval bounds and the reconstructed epoch, and a
  mart can filter it out by minimum evidence class

### Requirement: The ledger is flat-projectable to the warehouse

Each event SHALL be projectable to a single flat row carrying the envelope-compatible columns
(`event_id`, `event_type`, subject type and key, `effective_at`, `recorded_at`, `producer`,
`schema_version`, `rule_version`, `correlation_id`, `causation_id`, actor fields, `evidence`,
`payload` as parseable JSON) so the warehouse can dedupe by `event_id` and independently re-derive
state by fold for reconciliation.

#### Scenario: Independent re-derivation matches co-committed state

- **GIVEN** the full event history for a subject landed in the warehouse
- **WHEN** state is re-derived by folding events in `effective_at` order (ties by `recorded_at`)
- **THEN** the derived state equals the ledger's co-committed current state for that subject
