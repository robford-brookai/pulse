# projection-conformance Specification

## Purpose
The check a ledger-owned family gets: a consumer's projected state must equal the ledger's
current state for every subject and must cite the ledger sequence it was applied from, so a
projection is provably a view of the ledger and not a parallel store.
## Requirements
### Requirement: Projected state equals ledger current state per subject
For each registered consumer of a ledger-owned family, the sweep SHALL compare the consumer's
projected state with the ledger's current state per `(subject_type, subject_key)` as of one ledger
head snapshot taken at the start of the run. An equal pair SHALL count as an agreement. An unequal
pair SHALL be reported as a divergence naming the subject key, the consumer, and the field names
that differ, never the values.

#### Scenario: Agreement
- **GIVEN** a Twenty board card whose state and `ledger_seq` match the ledger's current state for
  its subject
- **WHEN** the sweep compares them
- **THEN** the pair counts as an agreement

#### Scenario: Divergence names the subject, never the value
- **GIVEN** a board card whose state differs from the ledger's current state for its subject
- **WHEN** the sweep compares them
- **THEN** the receipt reports a divergence of kind `state` for that subject key and consumer,
  naming the differing field, and carries neither value

#### Scenario: Events after the snapshot are not counted
- **GIVEN** an event committed to the ledger while the sweep is running
- **WHEN** the run completes
- **THEN** subjects that changed after the snapshot are compared against the snapshot only, and
  the receipt counts them as `in_flight` rather than as divergences

### Requirement: Every projected row cites the ledger sequence it was applied from
A consumer row SHALL cite the `ledger_seq` of the event it reflects. A row whose citation is behind
the ledger head for its subject by more than the consumer's freshness budget SHALL be reported as
a divergence of kind `lag`. A row with no citation SHALL be reported as `uncitable`. Citation is
the pass predicate: a consumer whose rows agree by value but cannot cite is not conformant.

#### Scenario: A lagging row is lag, not disagreement
- **GIVEN** a board card whose state equals the ledger's but whose cited `ledger_seq` is behind the
  subject's head by more than the projection's freshness budget
- **WHEN** the sweep compares them
- **THEN** the receipt reports a divergence of kind `lag` for that subject and consumer

#### Scenario: A row without a citation is uncitable
- **GIVEN** a consumer row for a ledger-owned subject that carries no `ledger_seq`
- **WHEN** the sweep compares it
- **THEN** the receipt counts it as `uncitable` for that consumer, regardless of whether its state
  happens to match

### Requirement: Consumers that cannot cite at all are reported as a class
A consumer registered as unable to cite ledger sequences (no `ledger_seq` on any row) SHALL be
reported on every run as an uncitable consumer with its row count for the family, and SHALL NOT be
compared row by row. The report names the retirement change that owns the consumer.

#### Scenario: The patients table is reported, not compared
- **GIVEN** graph-projection's `patients` table registered as an uncitable consumer of the
  `enrollment` family
- **WHEN** the sweep runs
- **THEN** the receipt reports the consumer as uncitable with its row count and the owning
  change's name, and performs no per-row comparison for it

### Requirement: Warehouse conformance folds the landed events per subject
For the warehouse consumer, the sweep SHALL compare the ledger's current state with the state
folded from the landed events per subject (latest event by ledger sequence), over pulse-owned
comparison SQL, bounded below by the history floor. A subject present in the ledger but absent
from the landing after the floor SHALL be reported as a divergence of kind `missing`; a subject
present in the landing but unknown to the ledger SHALL be reported as `orphan`.

#### Scenario: A missing landed event is a divergence
- **GIVEN** a subject whose latest ledger event, committed after the floor, has not landed in the
  warehouse within the landing's freshness budget
- **WHEN** the warehouse sweep runs
- **THEN** the receipt reports a divergence of kind `missing` for that subject

#### Scenario: A landed event the ledger does not know is an orphan
- **GIVEN** a landed event whose subject key does not exist in the ledger
- **WHEN** the warehouse sweep runs
- **THEN** the receipt reports a divergence of kind `orphan` for that subject key

### Requirement: Divergences are named, not averaged away, and nothing is corrected
Every divergence SHALL appear in the receipt individually by subject key; the sweep SHALL NOT
summarize divergences into a rate without the underlying keys, and SHALL NOT write to the ledger
or to any projection. The receipt SHALL name the remedy: the projection's authoritative rebuild.

#### Scenario: One divergence is one named line
- **GIVEN** exactly one board card that disagrees with the ledger
- **WHEN** the sweep runs
- **THEN** the receipt contains that subject key with its consumer and kind, the totals reflect one
  divergence, and neither the ledger nor the board is modified
