## Purpose

One governed place that answers "what crosses PULSE's boundary, in which direction, through
which seam, as whom, and is it real yet" — replacing a legacy inventory of where patient facts
happen to live with a registry an integrator can act on.

## ADDED Requirements

### Requirement: Every system crossing the boundary has a registry entry

A system that declares into PULSE, consumes PULSE's published surfaces, or both SHALL have an
entry in the producer registry in `docs/contracts/`. Each entry SHALL state, at minimum: the
system's name; **direction** (declares in / consumes out / both); **seam** (command API,
delivered export landed in the warehouse, bus subscription, or library entrypoint);
**credential and actor id** as the ledger will see it (D15 — attribution is authentication, so
the actor is derived from the credential and never read from a body); the **grain** it declares
or reads; and **status** from a fixed vocabulary: `shipped`, `spec-only`, `planned`, `blocked`,
or `excluded-by-design`. An `excluded-by-design` entry states the direction the system
*would* have if integrated — the hypothetical crossing — with the Notes cell carrying why it
never does; the fixed Direction vocabulary has no "n/a" value by design, so an absence of
direction can never be read as an answer.

#### Scenario: A registry entry names its seam and its actor

- **GIVEN** any entry in the producer registry
- **WHEN** it is read
- **THEN** direction, seam, credential/actor id, grain, and status are all present, and status
  is one of the fixed vocabulary values

#### Scenario: Deliberate exclusions are entries, not omissions

- **GIVEN** a system PULSE has decided not to integrate with — a pipeline that stays in its own
  tool, or a surface mirrored without a ledger machine
- **WHEN** the registry is read
- **THEN** that system appears with status `excluded-by-design` and the reason, so an absence is
  never ambiguous between "not yet" and "never"

### Requirement: The registry supersedes the legacy surface inventory

The registry SHALL be the authoritative list, and the legacy "~11 surfaces" inventory SHALL be
marked superseded and cross-linked as historical context — it describes where facts lived before
the connector architecture, mixes vendor systems with infrastructure, and states no direction or
seam. Consumers SHALL read the registry, never the legacy list, to determine how to integrate.

#### Scenario: The legacy list points forward

- **GIVEN** the legacy surface inventory document
- **WHEN** a reader reaches its list of surfaces
- **THEN** a superseded note names the registry as the authoritative source

### Requirement: An unregistered producer is a defect, not a variant

A system found declaring into PULSE without a registry entry SHALL be treated as a defect in the
same way the producer-ingress policy treats a state-asserting producer schema: the fix is a
registry entry and, where the declaration is state-asserting, an ingress that follows the
sanctioned pattern. There SHALL be no grandfathering.

#### Scenario: A new writer credential without an entry fails review

- **GIVEN** a change that introduces a new writer credential or ingress package
- **WHEN** the registry is checked for a matching entry
- **THEN** the absence is a finding the change must resolve before it lands

### Requirement: The registry records the revenue model as a two-direction source

The external CPT revenue model SHALL be registered with direction **both**: it consumes PULSE's
published surfaces to learn what to evaluate (enrollment and coverage state, the billing
episode's counters), and declares `billing_eligibility` verdicts in through the command API under
its own credential. The entry SHALL state that it declares qualification only, never an amount,
citing `billing-computation-boundary`.

#### Scenario: The revenue model's entry states both directions and the amount-free rule

- **GIVEN** the registry entry for the CPT revenue model
- **WHEN** it is read
- **THEN** direction is `both`, the inbound seam is the command API under its own credential, the
  outbound seam is the published surface it reads, and the entry states that no monetary value
  crosses into PULSE
