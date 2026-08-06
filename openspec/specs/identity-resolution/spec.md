# identity-resolution Specification

## Purpose
Defines how match decisions become ledger commands — resolve, mint-then-resolve, or quarantine —
how quarantine holds a Referral for human review, and how event consumption stays safe under
redelivery.
## Requirements
### Requirement: A match resolves the referral and attaches new identifiers

A match decision SHALL declare `resolve_referral` for the matched person, and SHALL declare
`attach_identifier` for each source identifier the referral carries that the person does not yet
hold. Identifiers the person already holds are not re-attached.

#### Scenario: Match with a new source identifier

- **GIVEN** a match on person P where the referral carries identifier `(S, V)` not yet attached
  to P
- **WHEN** the resolver acts on the decision
- **THEN** `resolve_referral` is declared for P and `attach_identifier` binds `(S, V)` to P, both
  carrying the decision's evidence

### Requirement: A mint creates the person, then resolves

A mint decision SHALL declare `mint_person` (minting a new TIDE key), then `resolve_referral` to
the minted person, then attach the referral's source identifiers — in that order, so the referral
never resolves to a person that does not exist.

#### Scenario: Mint then resolve

- **GIVEN** a mint decision for a referral carrying identifier `(S, V)`
- **WHEN** the resolver acts on the decision
- **THEN** `mint_person` commits first, `resolve_referral` names the minted person, and `(S, V)`
  is attached to it

### Requirement: Ambiguity quarantines, it never resolves

An ambiguous decision SHALL leave the Referral in `received`: the resolver declares a
`resolution_hold` fact (committable with no `to_state` — no transition, no state re-fold) and
enqueues the subject on `ledger.review_queue`. A subject SHALL be pending at most once. The
queue row's candidate set SHALL hold pseudonymous person keys only — a reviewer follows those
keys back to this service's evidence record; demographics never enter the queue.

#### Scenario: Two-candidate ambiguity quarantines

- **GIVEN** an ambiguous decision with two candidate persons
- **WHEN** the resolver acts on the decision
- **THEN** a `resolution_hold` fact commits, the Referral's current state remains `received`, and
  a review-queue row exists holding the two pseudonymous person keys and no demographic fields

#### Scenario: Re-delivery of a quarantined referral does not double-enqueue

- **GIVEN** a referral already pending on the review queue
- **WHEN** the same referral is processed again
- **THEN** the subject remains pending exactly once and no duplicate hold or queue row is created

### Requirement: Every resolution command carries evidence and an idempotency key

Every command the resolver declares SHALL carry the decision's evidence (matched-on fields, rule
id, candidate set size) and a D16 idempotency key, so any replay of the same logical resolution
is a no-op at the ledger.

#### Scenario: Replayed resolution produces one event

- **GIVEN** a resolution whose commands were already committed
- **WHEN** the identical resolution is submitted again
- **THEN** the ledger records no new events for those commands

### Requirement: Consumption is one referral per invocation, safe under redelivery

The service SHALL consume `referral.received` events via the platform consumer convention —
receive/process/delete with `event_id` dedupe, delete only after the handler returns — processing
one referral per invocation. A crash before completion SHALL result in redelivery, and redelivery
SHALL converge to the same outcome with no duplicate effects. No test SHALL make a live network
call.

#### Scenario: Crash before delete redelivers safely

- **GIVEN** a handler that committed its commands but crashed before the queue delete
- **WHEN** the event is redelivered
- **THEN** processing completes, idempotency makes the commands replays, and the final ledger
  state is identical to a single clean run

### Requirement: The quarantine reviewer has a documented procedure

A reviewer runbook SHALL document draining the quarantine queue: how to read a decision's
evidence, the disposition commands for each outcome, and the merge-by-command path for post-hoc
corrections (`merge_person` is the ledger's command — referenced, not rebuilt here).

#### Scenario: Runbook covers evidence, dispositions, and merge

- **GIVEN** the published reviewer runbook
- **WHEN** a reviewer follows it for a quarantined referral
- **THEN** it explains reading the evidence record from pseudonymous keys, lists the disposition
  commands, and links the merge-by-command correction path
