## Purpose

Reconciles ledger CommunicationConsent against the Customer.io suppression export on a daily
sweep, declaring corrections where they disagree — Customer.io is the authority for every
conflict, per D9.

## ADDED Requirements

### Requirement: Customer.io wins every conflict

The sweep SHALL parse a delivered Customer.io suppression export (CSV, fixture-pinned format),
diff it against ledger CommunicationConsent current state, and declare a
`record_communication_consent` correction for every disagreement — in both directions. The export
is authoritative per D9: an opt-out present in the export but missing from the ledger becomes an
opt-out correction, and a ledger opt-out the export contradicts becomes an opt-in correction. The
ledger is never treated as authoritative over the export.

#### Scenario: Opt-out missing from the ledger

- **GIVEN** an export row suppressing a subject the ledger shows as consented
- **WHEN** the sweep runs
- **THEN** an opt-out correction is declared for that subject

#### Scenario: Ledger opt-out the export contradicts

- **GIVEN** a subject the ledger shows as opted out and the export shows as not suppressed
- **WHEN** the sweep runs
- **THEN** an opt-in correction is declared for that subject

### Requirement: Corrections carry reconciliation attribution and provenance

Every correction SHALL be declared with actor `reconciliation` and SHALL carry provenance
referencing the export row that produced it, so any corrected consent state traces back to the
authority that dictated it. Declarations SHALL carry D16 idempotency keys so a re-run of the same
export replays rather than double-declaring.

#### Scenario: A correction is attributed and traceable

- **GIVEN** a conflict between an export row and ledger state
- **WHEN** the correction is declared
- **THEN** the command's actor is `reconciliation` and its payload references the export row, and
  re-running the sweep on the same export classifies the same correction as `replayed`

### Requirement: The sweep emits a drift receipt and never drops rows

Every run SHALL emit a drift receipt with the counts of agreements, corrections (by direction),
and unparseable rows. Rows that fail to parse SHALL be counted and attached to the receipt —
never silently dropped — and SHALL NOT abort the sweep of the remaining rows. Agreements produce
no writes.

#### Scenario: Agreements produce no writes

- **GIVEN** an export that fully agrees with ledger state
- **WHEN** the sweep runs
- **THEN** no commands are declared and the receipt reports every row as an agreement

#### Scenario: Malformed rows are counted and attached

- **GIVEN** an export containing malformed rows among valid ones
- **WHEN** the sweep runs
- **THEN** the valid rows are processed, the receipt counts the malformed rows and attaches them,
  and none are dropped without a trace
