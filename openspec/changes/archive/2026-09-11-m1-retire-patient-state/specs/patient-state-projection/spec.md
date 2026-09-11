## Purpose

The `patients` table in graph-projection is a view of the ledger's `enrollment` family: rows are
minted and their status kept only by applying ledger events, every row cites the ledger sequence
it reflects, and no other writer touches the status column.

## ADDED Requirements

### Requirement: Only the ledger projection mints or updates a patient row
The `patients` table SHALL be written only by the patient-state projection handler applying
ledger events from the `patient-state` feed. No other handler, service, migration data step, or
operator path SHALL insert a `patients` row or update `enrollment_status`. A repository gate SHALL
fail when any code outside the projection handler issues an `INSERT` into or `UPDATE` against
`patients`, and the database role every non-projection service uses SHALL hold select-only
privileges on the table.

#### Scenario: An alert for an unknown patient mints nothing
- **GIVEN** an alert event for a patient id the ledger has never minted
- **WHEN** the alerts handler applies it
- **THEN** the alert row lands, no `patients` row is created, and the alert is visible as an orphan
  to the conformance sweep

#### Scenario: A stray writer is refused by the gate
- **GIVEN** a change adding `INSERT INTO patients` to any module other than the projection handler
- **WHEN** the repository gate runs
- **THEN** it fails naming the file

### Requirement: A row is minted by the first enrollment event and keyed by the canonical patient id
The projection SHALL create a `patients` row when it applies the first `enrollment` event for a
subject, keyed by the canonical patient id that subject resolves to, with `enrollment_status`
equal to the event's resulting catalog state and `ledger_seq` equal to the event's ledger
sequence. `enrollment_status` SHALL hold only names from the catalog's `enrollment` family
(`pending_start`, `active`, `on_hold`, `ended`) for projected rows (guaranteed by the ledger
write-path validation against the catalog; the projection does not re-encode the family). A
subject that does not resolve to a canonical patient id SHALL park without failing the consumer,
as the board projection does.

#### Scenario: First enrollment event mints the row
- **GIVEN** no `patients` row for canonical patient P
- **WHEN** the projection applies P's `enrollment` event landing in `pending_start` at ledger
  sequence 41
- **THEN** a row exists for P with `enrollment_status = pending_start` and `ledger_seq = 41`

#### Scenario: A hardcoded default never appears
- **GIVEN** the projection handler and the schema after this change
- **WHEN** any row is created
- **THEN** its `enrollment_status` came from a ledger event, never from a column or model default

### Requirement: Apply is monotonic on the ledger sequence
The projection SHALL apply an `enrollment` event to a row only if the event's ledger sequence is
greater than the row's recorded `ledger_seq`; an older or equal event SHALL be a no-op that is
counted, not an error. A redelivered event SHALL leave the row unchanged.

#### Scenario: A late event does not regress state
- **GIVEN** a row at `active` citing sequence 50
- **WHEN** the projection receives the subject's event for sequence 47 (`pending_start`)
- **THEN** the row still reads `active` at sequence 50 and the skip is counted

### Requirement: Legacy rows are marked, never overwritten
A `patients` row that predates the projection SHALL keep its existing `enrollment_status` value
and SHALL carry a null `ledger_seq`. The projection SHALL NOT modify a legacy row until a ledger
event for its canonical patient id arrives, at which point the row is adopted (status and
`ledger_seq` set from the event). Every read surface SHALL be able to tell a legacy row from a
projected one by the null citation.

#### Scenario: A legacy row is reported as uncitable, not corrected
- **GIVEN** a row minted by the retired bootstrap insert, `enrollment_status = pending`,
  `ledger_seq` null
- **WHEN** the conformance sweep runs
- **THEN** the row is counted as uncitable for the `patients` consumer and its value is untouched

#### Scenario: Genesis adopts a legacy row
- **GIVEN** the same legacy row
- **WHEN** the first ledger `enrollment` event for its canonical patient id is applied
- **THEN** the row's status and `ledger_seq` come from that event and it leaves the uncitable count

### Requirement: The read surfaces present the projected state and its citation
`patient_graph_summary` SHALL expose `enrollment_status` and `ledger_seq` per patient; the
stacte-bridge schema descriptions SHALL state that `enrollment_status` is projected from the ledger
and read-only; the Slack patient status line SHALL render the catalog state and SHALL mark a row
with no citation as legacy rather than presenting `pending` as a status.

#### Scenario: Slack shows a legacy row honestly
- **GIVEN** a `patients` row with `ledger_seq` null
- **WHEN** the Slack status command renders it
- **THEN** the status line says the value is legacy and unverified against the ledger

#### Scenario: Slack shows a projected row
- **GIVEN** a `patients` row at `on_hold` citing sequence 88
- **WHEN** the Slack status command renders it
- **THEN** the status line reads `on_hold` and no legacy marker appears

### Requirement: No asserted enrollment state travels the bus from a producer
Producers under `packages/ocean` SHALL NOT place an enrollment status into a `patient.*` event
payload. The impilo normalizer's `patient.*` payload SHALL carry the patient identifier and source
type only.

#### Scenario: The normalizer emits no status
- **GIVEN** an impilo patient record
- **WHEN** the normalizer builds the `patient.*` event
- **THEN** the payload has no `enrollment_status` key

### Requirement: The projection is a citable consumer for the conformance sweep
The `reconciliation-sweeps` consumer registry SHALL register `graph-projection-patients` with
`cite_field = ledger_seq` for the `enrollment` family once the projection is live, so the sweep
compares projected rows with the ledger per subject and reports legacy rows as uncitable, exactly
as it treats the board.

#### Scenario: A projected row agrees with the ledger
- **GIVEN** a projected row at `active` citing sequence 50 and the ledger's current state for that
  subject at `active`, head 50
- **WHEN** the conformance sweep runs
- **THEN** the pair counts as an agreement for the `graph-projection-patients` consumer
