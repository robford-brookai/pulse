## Purpose

The line between PULSE and Brook's billing economics, stated as a contract rather than left to
be inferred from an absent field: PULSE records that an episode qualified and which rule version
decided it; every code, rate, amount, and optimization belongs to a system outside PULSE.

## ADDED Requirements

### Requirement: PULSE computes no monetary value

No PULSE component SHALL compute, derive, or infer a monetary value — a rate, an allowed amount,
a reimbursement, a revenue figure, a copay, or a claim total. PULSE SHALL NOT hold a CPT or
HCPCS code as ledger state, a fee schedule, a partner rate card, or a code-ladder rule. These
belong to the external revenue model registered per `producer-registry`; PULSE records only the
qualification outcome that model declares.

#### Scenario: No catalog subject carries a monetary field

- **GIVEN** the committed state catalog and the ledger schema
- **WHEN** every subject's field set is inspected
- **THEN** no field is a currency, rate, amount, or code-valued billing field — the billing
  episode's own fields are counters (`accrued_minutes`, `reading_days`), states, stamps, and a
  `rule_version` string

#### Scenario: A command asserting an amount is refused

- **GIVEN** the command API
- **WHEN** a command body carries a monetary field for a billing subject
- **THEN** the command is rejected as invalid rather than committed with the field ignored — an
  amount silently dropped is worse than an amount refused

### Requirement: Qualification is recorded as a verdict plus its deciding rule version

PULSE SHALL record billing qualification as the catalog's trinary outcome
(`qualified` / `not_qualified`, with `indeterminate` moving no state) paired with the
`rule_version` that produced it and a `lineage_ref` to the evidence held by the deciding system.
PULSE SHALL NOT re-derive, second-guess, or recompute a declared verdict.

#### Scenario: A verdict moves state and records its provenance

- **GIVEN** a `billing_eligibility` verdict declared by the registered revenue model
- **WHEN** it commits
- **THEN** the episode's state moves per the catalog's adjacency and the event carries
  `rule_version` and `lineage_ref`, so the decision is attributable to a version of a rule set
  PULSE does not hold

#### Scenario: Nothing downstream recomputes the verdict

- **GIVEN** a committed qualification verdict
- **WHEN** any projection or consumer renders the episode
- **THEN** it displays the recorded outcome and never evaluates eligibility rules itself

### Requirement: Money may appear in evidence, never in state

A verdict's payload and `lineage_ref` MAY reference monetary detail the deciding system used —
a copay figure, a benefit category, a rate card version — because evidence is opaque to PULSE.
That detail SHALL NOT be promoted into the state vocabulary, a catalog field, or a projection's
written surface.

#### Scenario: Benefit detail stays in evidence

- **GIVEN** a verdict whose payload carries a copay amount as evidence
- **WHEN** the verdict commits and projects
- **THEN** the amount is retrievable only from the event's payload or lineage, and no catalog
  state, status field, or projected board column carries it

### Requirement: The boundary is stated where an integrator will look

The published contract surface SHALL state this boundary in prose: that PULSE produces
billing-ready episodes and records qualification, that clinics submit claims, and that codes,
rates, and revenue optimization live in the registered external model. A reader of
`docs/contracts/` SHALL be able to answer "does PULSE price anything?" without reading a
migration assessment.

#### Scenario: The contract answers the question directly

- **GIVEN** the published and consumed contract documents
- **WHEN** a reader searches them for billing scope
- **THEN** the boundary statement is present, names the external model and the D6 terminal
  boundary (`reported`), and links the registry entry that carries the seam
