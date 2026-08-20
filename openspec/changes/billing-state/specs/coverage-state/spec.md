## Purpose

Coverage as a ledger subject: the continuously-known, enumerable, broadcast answer to "is this
patient's insurance coverage verified and active" — recorded as state transitions justified by
declared eligibility and benefits-verification verdicts, never inferred from verdict history by
each consumer.

## ADDED Requirements

### Requirement: Coverage is a ledger-owned subject at patient × payer grain

The catalog SHALL define a `coverage` subject (`ownership: ledger`) whose grain is one subject
per patient × payer, with the coarse state machine
`unverified → verified_active | verified_inactive`, `verified_active ⇄ verified_inactive`,
either verified state → `lapsed` (re-verifiable), and terminal `terminated`. Benefit detail —
QMB status, benefit categories, copay — SHALL live in verdict payload and `lineage_ref`, never
in the state vocabulary.

#### Scenario: A verified coverage carries its detail in evidence, not state

- **GIVEN** a benefits-verification verdict whose payload carries QMB status
- **WHEN** its paired transition commits
- **THEN** the subject's state is a coarse vocabulary value and the QMB detail is reachable
  only through the verdict's payload and lineage

### Requirement: The record admits the coverage subject

The ledger schema SHALL accept `coverage` in `events`, `current_state`, and `review_queue` —
the three subject-type CHECK constraints widen by migration in the same change that adds the
subject to the catalog, so a catalog-legal coverage transition can never validate but fail to
commit.

#### Scenario: A catalog-legal coverage transition commits

- **GIVEN** the migrated schema and a legal coverage transition command
- **WHEN** it is submitted
- **THEN** it validates against the generated adjacency and commits — event, `current_state`
  fold, and outbox row in one transaction

### Requirement: The first verdict for an unseen coverage key mints the subject

A verdict for a patient × payer key with no existing coverage subject SHALL mint the subject at
its derived initial state (`unverified`) and apply the paired transition in the same run — no
separate registration step, no manual minting.

#### Scenario: First declare mints and transitions

- **GIVEN** a coverage-eligibility verdict row for a patient × payer key the ledger has never
  seen
- **WHEN** the relay declares it
- **THEN** the coverage subject exists afterward with the transition applied, and a second
  verdict for the same key transitions without re-minting

### Requirement: Coverage is enumerable from current state

Clock-driven and operational reads SHALL enumerate coverage subjects by state from the ledger's
`current_state` (the `enumerate_state` read), never from a projection or by folding verdict
history.

#### Scenario: Lapsed coverage enumerates from the ledger

- **GIVEN** coverage subjects in assorted states
- **WHEN** a job enumerates `lapsed`
- **THEN** exactly the lapsed subjects return, read from `current_state`

### Requirement: Payer identifiers never reach logs or leave the boundary

Coverage processing SHALL log subject keys only. Payer identifiers, member ids, and any
coverage payload value SHALL never appear in logs, receipts, metrics, or error messages, and
identifier registry entries SHALL follow the existing sha256-digest posture.

#### Scenario: A failure log carries no payer value

- **GIVEN** a scripted failure whose row carries a synthetic payer identifier
- **WHEN** the failure is logged
- **THEN** the log line carries the subject key and error class only, and the synthetic payer
  value appears nowhere in the output
