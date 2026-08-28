## Purpose

Defines the two-tier deterministic match decision — exact identifier, then composite — with the
mint/match/quarantine trichotomy, the evidence carried by every decision, determinism guarantees,
and the entrypoint stability genesis depends on.

## ADDED Requirements

### Requirement: Exact identifier match wins outright

An exact match on the `(system, value)` of any ExternalIdentifier carried by the referral SHALL
resolve to that identifier's person without consulting the composite tier. Uniqueness of
`(system, value)` is structural (the `external_identifiers` primary key), so this tier yields at
most one person by construction.

#### Scenario: Exact identifier hit short-circuits

- **GIVEN** a person holding ExternalIdentifier `(S, V)` and a referral carrying `(S, V)` with
  demographics that would composite-match a different person
- **WHEN** the matcher runs
- **THEN** the decision is a match on the identifier's person, and the evidence names the
  identifier tier

#### Scenario: Identifiers held by two different persons quarantine

- **GIVEN** a referral carrying two ExternalIdentifiers held by two different persons
- **WHEN** the matcher runs
- **THEN** the decision is ambiguous, carrying both holders, and no automatic choice between
  them is ever made — the tier looks up every carried identifier, and a split is quarantined
  under its own rule id (`identifier_conflict`) rather than resolved to the first holder

### Requirement: The composite tier is a strict trichotomy

When no exact identifier matches, the matcher SHALL look up candidates by the composite match-key
digest and decide by candidate count alone: zero candidates SHALL mint a new person, exactly one
SHALL match it, and more than one SHALL quarantine as ambiguous. **v1 is deterministic only** —
no probabilistic scoring, no similarity thresholds, no tie-breaking heuristics: a wrong
auto-merge in a HIPAA system is a reportable event, so ambiguity always goes to a human.

#### Scenario: Zero candidates mints

- **GIVEN** a referral whose identifiers are unknown and whose composite digest has no candidates
- **WHEN** the matcher runs
- **THEN** the decision is to mint a new person

#### Scenario: One candidate matches

- **GIVEN** a referral whose composite digest has exactly one candidate person
- **WHEN** the matcher runs
- **THEN** the decision is a match on that person

#### Scenario: Two candidates quarantine

- **GIVEN** a referral whose composite digest has two candidate persons
- **WHEN** the matcher runs
- **THEN** the decision is ambiguous, carrying both candidates, and no automatic choice between
  them is ever made

### Requirement: A near-miss must not match

A record that agrees on some fields but disagrees on any composite component SHALL NOT match:
same name with a different DOB is a different composite, hence a different digest, hence never a
candidate. The fixture set SHALL include this must-not-match case explicitly.

#### Scenario: Same name, different DOB does not match

- **GIVEN** an existing person and a referral with the identical normalized name and sex but a
  different DOB
- **WHEN** the matcher runs
- **THEN** the existing person is not a candidate and the decision is to mint

### Requirement: Every decision carries evidence

Every match decision SHALL carry evidence: the matched-on fields, the rule id that decided
(identifier tier or composite tier), and the candidate set size. Evidence SHALL be sufficient for
a reviewer to reconstruct why the decision was made without re-running the matcher.

#### Scenario: Evidence names fields, rule, and candidate count

- **GIVEN** any resolution decision (match, mint, or ambiguous)
- **WHEN** the decision is inspected
- **THEN** it carries the matched-on fields, a rule id, and the candidate set size

### Requirement: Matching is order-independent and re-run-identical

Resolution of any input set SHALL be order-independent and re-run-identical: the same referrals
in any order, resolved any number of times, SHALL produce the same decisions with the same
evidence, and replayed commands SHALL be idempotent.

#### Scenario: Property test over fixture sets

- **GIVEN** a fixture set of referrals
- **WHEN** the set is resolved in shuffled orders and repeatedly
- **THEN** every run produces identical decisions and identical evidence, and command replays
  produce no new effects

### Requirement: The matcher entrypoint is stable for genesis

The matcher SHALL be invocable as a library entrypoint independent of the event-consumption
service, and that entrypoint's signature and decision types are a published contract: genesis
adjudication calls it in batch with its own harness. Changes to the entrypoint follow the
published-contract rules, not internal refactoring freedom.

#### Scenario: Batch invocation without the service

- **GIVEN** a caller importing the matcher entrypoint directly (no queue, no service process)
- **WHEN** it submits a referral's demographics and identifiers
- **THEN** it receives the same typed decision, with evidence, that the service path would produce
