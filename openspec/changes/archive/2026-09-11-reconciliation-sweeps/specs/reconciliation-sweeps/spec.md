## Purpose

Per-family referee sweeps that check every projection of the ledger against the ledger on a
schedule, declaring corrections only where an external system of record owns the family and
reporting, never writing, everywhere else.

## ADDED Requirements

### Requirement: Every catalog family has exactly one sweep kind, derived from its ownership
The sweep registry SHALL derive one sweep kind per family from the catalog's `ownership` field:
`export_diff` for a family whose ownership is `recorded` (an external system of record adjudicates
and exports), `projection_conformance` for a family whose ownership is `ledger`. A family with any
other ownership value, or absent from the catalog, SHALL be refused at registry load with the
family named. The registry SHALL be built from the released catalog version, never a hand-kept
list, so a catalog release that adds a family adds a sweep.

#### Scenario: A recorded family gets the export diff
- **GIVEN** the catalog marks `communication_consent` as `ownership: recorded`
- **WHEN** the registry loads
- **THEN** the family's sweep kind is `export_diff` and its entry is the existing consent sweep

#### Scenario: A ledger family gets projection conformance
- **GIVEN** the catalog marks `enrollment` as `ownership: ledger`
- **WHEN** the registry loads
- **THEN** the family's sweep kind is `projection_conformance`

#### Scenario: An unknown ownership is refused
- **GIVEN** a catalog entry whose `ownership` is neither `recorded` nor `ledger`
- **WHEN** the registry loads
- **THEN** loading fails naming the family and the value, and no sweep runs

### Requirement: A ledger-owned family's sweep never writes the ledger
A `projection_conformance` sweep SHALL hold no ledger writer credential and SHALL declare no
command. Every divergence it finds is reported for the projection's owner to repair through the
authoritative rebuild; the ledger is the record and is not adjusted to match a copy of itself.
The credential-posture gate SHALL count the sweep's credentials as read-only.

#### Scenario: A divergence produces a report, not a correction
- **GIVEN** a consumer row for an `enrollment` subject that disagrees with the ledger
- **WHEN** the sweep runs
- **THEN** the receipt names the subject key and the consumer, and no command reaches the command
  API

#### Scenario: The sweep's configuration carries no writer credential
- **GIVEN** the sweep's configuration for a ledger-owned family
- **WHEN** the credential-posture gate inspects it
- **THEN** it finds ledger read, projection read and warehouse read credentials only

### Requirement: A recorded family's sweep keeps its correction behavior
An `export_diff` sweep SHALL keep the behavior its own specification defines: the external export
wins every conflict and corrections are declared under the `reconciliation` writer credential.
Registering the consent sweep in the registry SHALL change none of its observable behavior.

#### Scenario: The consent sweep runs unchanged as a registry entry
- **GIVEN** a consent export that contradicts ledger state for one subject
- **WHEN** the registry dispatches the `communication_consent` sweep
- **THEN** one correction is declared with actor `reconciliation`, exactly as before this change

### Requirement: Sweeps run on a schedule and every run ends in a receipt
Each registered family SHALL have a scheduled daily run. Every run SHALL end in exactly one
machine-parsable receipt line per family carrying the run date, the family, the sweep kind, the
lower bound swept from, and counts of agreements, divergences by kind, uncitable rows, malformed
rows, pre-floor subjects, and unconfigured consumers. A registered consumer whose source this
environment does not host SHALL be marked `unconfigured` (boolean, default false) in its
per-consumer receipt entry, with every other per-consumer field zero, so the receipt still
accounts for every registered consumer of the family without inventing a count no row backs.
Receipts SHALL carry subject keys and counts only, never payload values, payer identifiers, or
demographics, and SHALL be tagged so the observability plan's drift trend can read them.

#### Scenario: A clean run leaves a countable receipt
- **GIVEN** a family whose projections all agree with the ledger
- **WHEN** the scheduled run completes
- **THEN** one receipt line reports zero divergences and zero uncitable rows for that family and
  date, and nothing else is written

#### Scenario: Malformed input is counted, never dropped
- **GIVEN** a projection read that returns rows the sweep cannot parse among valid ones
- **WHEN** the run completes
- **THEN** the valid rows are compared, the malformed rows are counted in the receipt, and the run
  exits nonzero only if no rows could be compared at all

#### Scenario: Ten clean receipts are readable as a streak
- **GIVEN** ten consecutive business days of receipts for one family with zero divergences
- **WHEN** an operator reads the receipt stream
- **THEN** the streak is computable from the receipt lines alone, without payload access

### Requirement: A consumer whose source this environment does not host is named, not faked
A `projection_conformance` sweep SHALL resolve every environment variable its consumers' sources
need before opening any connection, and SHALL fail startup naming the first required variable that
is unset. A consumer registered for the family whose source group is absent from the environment
entirely SHALL be reported in the receipt as `unconfigured` and skipped: it SHALL NOT count as a
divergence of any kind, SHALL NOT make the family `no_consumers`, and SHALL NOT prevent the
family's other consumers from comparing. A source group that is only partly configured SHALL fail
startup by name rather than be reported `unconfigured`.

#### Scenario: A missing variable fails startup by name
- **GIVEN** a required variable for the sweep's ledger read is unset
- **WHEN** the sweep starts
- **THEN** it fails naming that variable, before any source is connected, and names no value

#### Scenario: An environment without the graph database still sweeps enrollment
- **GIVEN** an environment that hosts no OCEAN graph database
- **WHEN** the `enrollment` sweep runs
- **THEN** `graph-projection-patients` is reported `unconfigured`, `twenty-board` and
  `warehouse-landing` compare their rows, and the receipt is not `no_consumers`

#### Scenario: A half-configured source is a fault, not an absence
- **GIVEN** a source group with some but not all of its variables set
- **WHEN** the sweep starts
- **THEN** it fails naming the missing variable rather than skipping that consumer

### Requirement: No sweep asserts divergence below the history floor
A sweep SHALL exclude from comparison any subject whose ledger history lies entirely before the
warehouse contract's completeness watermark (`min_complete_from`), SHALL count such subjects as
`pre_floor` rather than as divergences, and SHALL state the floor it applied in its receipt.

#### Scenario: A pre-watermark subject is excluded, not flagged
- **GIVEN** a subject whose only events precede the STG_EVENTS `min_complete_from` date
- **WHEN** the warehouse conformance sweep runs
- **THEN** the subject is counted as `pre_floor`, no divergence is reported for it, and the receipt
  states the floor date
