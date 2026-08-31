## Purpose

Billing and coverage rule evaluation inside pulse, event-driven: verdicts are computed when
the facts they depend on arrive, not when a batch job happens to run — so billing state is
continuous by construction and the warehouse mart stops being a write-path dependency.

## ADDED Requirements

### Requirement: Evaluation is event-driven, never batch-gated

The billing engine SHALL subscribe to the ledger's committed events and evaluate the affected
subject's eligibility and coverage rules when a relevant fact arrives (a billing episode
opens, coverage state changes, consent state changes). Declare-back latency SHALL be bounded
by event delivery plus evaluation time — never by any batch schedule. The engine SHALL NOT
read the warehouse to decide a verdict.

#### Scenario: A fact arrives, a verdict follows

- **GIVEN** an open billing episode whose eligibility rules are satisfied except for consent
- **WHEN** the consent event for that patient commits and reaches the engine
- **THEN** the engine evaluates that episode and declares its verdict without waiting for any
  scheduled run

### Requirement: The engine declares attributed, versioned verdict pairs

Every engine verdict SHALL be declared through the command API under the engine's own writer
credential, carrying the `rule_version` of the rule set that produced it, and SHALL follow
the registered pairing contract: verdict then paired transition, idempotency key derived from
the evaluation (D16) so the pair is replay-safe as a unit, `indeterminate` declaring evidence
with no transition. Monetary values SHALL never appear in a verdict payload, a state, a log,
or a receipt — the amount-free billing boundary applies at the engine's seam.

#### Scenario: Re-evaluating unchanged facts declares nothing new

- **GIVEN** a subject the engine already evaluated, with no new facts
- **WHEN** evaluation runs again for that subject
- **THEN** submissions classify as replayed and no new event exists

#### Scenario: No monetary value crosses the seam

- **GIVEN** a rule evaluation whose inputs include amount-bearing source data
- **WHEN** its verdict is declared and logged
- **THEN** the command payload, the receipt, and every log line carry qualification facts
  only — no monetary value appears anywhere downstream of the engine seam

### Requirement: Rules are ported with lineage, not re-imagined

The engine's rule logic SHALL be ported from the dbt verdict models with a documented mapping
from each dbt model/test to its pulse counterpart, and each ported rule SHALL carry a new
`rule_version` distinct from the mart's versions, so any verdict is attributable to exactly
one implementation.

#### Scenario: A verdict names its implementation

- **GIVEN** verdicts declared by the mart relay and by the engine during the parallel window
- **WHEN** any verdict event is inspected
- **THEN** its `rule_version` identifies which implementation produced it, unambiguously
