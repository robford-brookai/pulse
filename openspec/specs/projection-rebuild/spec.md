# projection-rebuild Specification

## Purpose
A projection is a window painted from the journal, and the proof that it is a window and not a
copy is that it can be destroyed and repainted from the journal alone, row for row. This
capability makes that rebuild a first-class, receipted operation.
## Requirements
### Requirement: A projection rebuilds from the journal alone
The board projection SHALL offer an authoritative rebuild that repaints its rows from the
ledger's committed events for a named scope, consuming no other source and holding no ledger
database credential.

#### Scenario: Destroy then rebuild is row-identical
- **WHEN** the projection's rows for a scope are captured, deleted, and the rebuild runs for
  that scope
- **THEN** the rebuilt rows equal the captured rows field for field, and the rebuild receipt
  reports the count rebuilt and zero differences

#### Scenario: A rebuild over intact rows changes nothing
- **WHEN** the rebuild runs for a scope whose rows already match the ledger
- **THEN** no row is written and the receipt reports zero changes

### Requirement: A rebuild respects the same ordering rules as live apply
The rebuild SHALL apply events in ledger sequence per subject and SHALL produce the same
final state as incremental apply would have, including for late-arriving and reversed events.

#### Scenario: A mixed history rebuilds to the live state
- **WHEN** a subject's journal holds forward, backdated, and reversal events and the rebuild
  runs
- **THEN** the rebuilt row equals the row incremental apply produced from the same events

### Requirement: A rebuild is receipted and reversible
Every rebuild SHALL end in a counted receipt (scope, rows read, rows written, differences
found) and SHALL be safe to rerun. A rebuild SHALL never delete rows outside its named scope.

#### Scenario: A rerun is a no-op
- **WHEN** the rebuild runs twice for the same scope with no intervening events
- **THEN** the second run writes nothing and both receipts are attributable to the operator
  who ran them

#### Scenario: Scope is honored
- **WHEN** the rebuild runs for one scope while rows exist for another
- **THEN** rows outside the named scope are untouched

