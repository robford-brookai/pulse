# billing-engine Specification

## Purpose
The in-pulse home for billing and coverage rule evaluation: a service on the connector kit that
folds per-subject facts from the ledger's committed events into its own store and holds the rule
logic ported from the dbt verdict models. This change delivers the engine's foundation — its
store, its fact fold, and its ported rules with lineage. Wiring evaluation to a declare, and
retiring the warehouse mart behind a reconciliation window, belong to the `billing-connector`
change (design.md decision 9; seeded in `design/delivery/billing-connector-seed.md`).
## Requirements
### Requirement: The engine store is a rebuildable fact cache, never a state of record

The engine SHALL keep its own store — a `billing_engine` schema under its own role and
credential, separate from the ledger's — holding per-subject fact snapshots and evaluation
receipts only. Every row SHALL be reconstructible by replaying the bus, so the store may be
dropped and rebuilt without loss. The fold SHALL apply each committed event to a subject at most
once, using a per-subject event high-water mark, and SHALL order competing facts by effective
time rather than arrival order. No state-of-record read SHALL target this schema: the engine's
store answers what the engine folded, never what the ledger holds.

#### Scenario: A redelivered event folds once

- **GIVEN** a committed event already folded into a subject's fact snapshot
- **WHEN** the queue delivers that same event again
- **THEN** the snapshot is unchanged and the subject's high-water mark does not move — the
  redelivery is a dedupe hit, not a second fold

#### Scenario: No state-of-record read targets the engine schema

- **GIVEN** any package outside `packages/billing` in the tree
- **WHEN** its sources are scanned for the ledger's canonical state-of-record reader
- **THEN** no module both calls that reader and references the `billing_engine` schema — the
  shadow-ledger shape is absent, and the gate fails against a planted violation

### Requirement: Rules are ported with lineage, not re-imagined

The engine's rule logic SHALL be ported from the dbt verdict models with a documented mapping
from each dbt model/test to its pulse counterpart, and each ported rule SHALL carry a new
`rule_version` distinct from the mart's versions, so any verdict is attributable to exactly
one implementation.

#### Scenario: A verdict names its implementation

- **GIVEN** verdicts declared by the mart relay and, once `billing-connector` ships, by the engine
- **WHEN** any verdict event is inspected
- **THEN** its `rule_version` identifies which implementation produced it, unambiguously
