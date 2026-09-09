## Purpose

The first connector built on the shared kit: it turns the billing engine's folded facts into
declared, attributed, versioned verdicts on the ledger the moment the facts change, under one
credential, with no warehouse on the write path and no monetary value crossing its seam.

## ADDED Requirements

### Requirement: Evaluation is event-driven, never batch-gated
The connector SHALL subscribe to the ledger's committed events and evaluate the affected
subject's registered verdict types when a relevant fact arrives (a billing episode opens or
changes, coverage state changes). Declare-back latency SHALL be bounded by event delivery plus
evaluation time, never by a batch schedule. The connector SHALL NOT read the warehouse to
decide a verdict.

#### Scenario: A fact arrives, a verdict follows
- **GIVEN** an open billing episode whose eligibility facts change in a way that flips the
  verdict
- **WHEN** that event commits and reaches the connector
- **THEN** the connector evaluates that episode and declares its verdict without waiting for
  any scheduled run

#### Scenario: Consent and enrollment fan-out wait for their fact
- **GIVEN** a consent or enrollment event for a patient with open billing episodes
- **WHEN** the event reaches the connector and no catalog fact links that subject to the
  episode subjects it affects
- **THEN** the connector records the event in the subject's facts, evaluates nothing, and
  counts it as `deferred` in the receipt

### Requirement: The connector evaluates the registered verdict types
The connector SHALL evaluate exactly the verdict types the billing rules package registers,
each with its `rule_version`, and SHALL refuse to start if a registered type has no rule
module or a rule module is unregistered.

#### Scenario: One registered type, one evaluation
- **WHEN** the rules package registers one verdict type and a subject's facts change
- **THEN** the connector evaluates that type only and the receipt names it

#### Scenario: A registry mismatch halts startup
- **WHEN** the registry and the rule modules disagree
- **THEN** the connector exits nonzero before consuming, naming the mismatch

### Requirement: Staleness comes from the connector's own watermark
The connector SHALL derive the `facts_stale` input from the age of the subject's fact
watermark against a configured threshold. A subject with no folded events SHALL evaluate as
indeterminate with the `awaiting_source` reason. No source-table recency SHALL be read.

#### Scenario: A stale watermark yields awaiting_source
- **GIVEN** a subject whose last folded event is older than the configured threshold
- **WHEN** it is evaluated
- **THEN** the outcome is indeterminate with reason `awaiting_source` and evidence declares
  with no transition

#### Scenario: A fresh watermark evaluates the rule
- **GIVEN** a subject whose last folded event is within the threshold
- **WHEN** it is evaluated
- **THEN** the rule module's outcome decides the verdict

### Requirement: The connector declares attributed, versioned verdict pairs
Every verdict SHALL be declared through the command API under the connector's own writer
credential, carrying the `rule_version` that produced it, following the registered pairing
contract: verdict then paired transition, idempotency key derived from the evaluation so the
pair is replay-safe as a unit, `indeterminate` declaring evidence with no transition. Each
evaluation SHALL be recorded in the engine's `evaluations` store with the declared event id.

#### Scenario: Re-evaluating unchanged facts declares nothing new
- **GIVEN** a subject the connector already evaluated, with no new facts
- **WHEN** evaluation runs again for that subject
- **THEN** submissions classify as replayed, no new event exists, and the receipt counts the
  replay

#### Scenario: A rejected transition keeps its evidence
- **GIVEN** a verdict whose paired transition is no longer legal for the subject
- **WHEN** the pair is declared
- **THEN** the verdict commits, the transition is counted as rejected with the catalog's
  reason, and state is unchanged

### Requirement: No monetary value crosses the seam
Monetary values SHALL never appear in a verdict payload, a state, a log line, or a receipt
produced by the connector.

#### Scenario: Amount-bearing inputs leave no trace
- **GIVEN** a rule evaluation whose inputs include amount-bearing source data
- **WHEN** its verdict is declared and logged
- **THEN** the command payload, the receipt, and every log line carry qualification facts
  only

### Requirement: One credential, names in config, values from the environment
The connector SHALL hold exactly one writer credential name plus its queue and ledger base
URL in configuration, SHALL read every value from the environment at startup, and SHALL hold
no ledger database connection string. Startup SHALL fail with the missing variable's name if
any value is absent.

#### Scenario: A missing value names itself
- **WHEN** the connector starts without one required environment variable
- **THEN** it exits nonzero naming that variable and nothing else

#### Scenario: The credential-posture gate discovers the package
- **WHEN** the workspace credential-posture gate runs
- **THEN** it discovers the connector package and finds one credential name, no ledger
  internals, and no credential value reachable by any log call

### Requirement: Every run ends in a counted receipt
The connector SHALL end every consume batch with one receipt line extending the kit's counted
receipt with `evaluated=N` and `deferred=N`, and the receipt SHALL carry counts and subject
keys only.

#### Scenario: The receipt shape is stable
- **WHEN** a batch completes
- **THEN** the receipt line matches the golden shape byte for byte apart from the counts
