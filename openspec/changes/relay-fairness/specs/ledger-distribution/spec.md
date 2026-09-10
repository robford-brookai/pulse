## MODIFIED Requirements

### Requirement: Relay is at-least-once with per-subject ordering

The relay SHALL publish pending non-dead-lettered outbox rows to the EventBridge bus at least once,
in per-subject sequence order; cross-subject ordering is not guaranteed. This is a publication-order
guarantee, not a subscriber arrival-order guarantee. A dead-lettered row SHALL cease blocking later
rows, and its manual redrive SHALL be treated as a possible late delivery by consumers. Consumers dedupe on `event_id` per the
event-transport envelope contract. Outbox-to-backbone lag SHALL meet p99 < 30 s.

The published envelope SHALL carry `subject_type`, `subject_key`, and `seq`: per-subject ordering is
only checkable by a consumer that can see the sequence it is meant to hold, and `key` alone does not
survive into the detail because EventBridge does not route on it. `effective_at` is emitted with
`occurred_at` beside it at the same value — the same alias pairing the write path accepts (decision
5), so a consumer written against either name reads one fact.

The publisher the relay builds on SHALL surface delivery failure to its caller. `ocean-broker`'s
`EventBridgePublisher` previously swallowed every rejection into its own `failed_webhooks` DLQ, which
would have made this entire retry-and-dead-letter policy vacuous — the relay could not distinguish a
delivered event from a dropped one. Its `on_failure="raise"` mode is what the relay uses; the default
is unchanged for every other publish site. A caller that already owns a durable queue must not have a
second, invisible copy of its failures filed elsewhere. If the platform wants this stated as a
cross-repo contract, `docs/contracts/consumes.md` is where it belongs.

#### Scenario: Redelivery is deduplicable

- **GIVEN** a relay retry after an ambiguous publish
- **WHEN** the same outbox row is published twice
- **THEN** both deliveries carry the same `event_id` and a deduping consumer processes the event
  once

#### Scenario: Per-subject order holds across retries

- **GIVEN** events 1..3 for one subject with event 2 failing transiently
- **WHEN** the relay retries
- **THEN** the relay publishes the subject's events in sequence order 1, 2, 3

#### Scenario: Transport reorder and late redrive preserve projection correctness

- **GIVEN** events delivered out of sequence, duplicate event ids, and an older manually redriven event
- **WHEN** existing projection consumers process these deliveries
- **THEN** duplicate suppression and each consumer's watermark/replay contract preserve the projection; subscriber arrival order is not assumed

## ADDED Requirements

### Requirement: Independent ready subjects receive bounded fair service

The relay SHALL visit each continuously eligible unlocked subject within one complete scan cycle over a fixed finite subject set. Per-pass subject work and per-subject publication work SHALL be bounded. Locked or backing-off subjects SHALL NOT consume all future selection opportunities; a backing-off head SHALL prevent later pending rows for that subject from bypassing it. Scheduling progress SHALL survive successive passes within a running worker, while restart SHALL preserve durable outbox delivery state.

#### Scenario: Skewed backlog cannot starve an independent subject

- **GIVEN** a fixed finite subject set with a large early-sorting backlog and a continuously due unlocked late-sorting subject
- **WHEN** the worker runs successive bounded passes through a complete scan cycle
- **THEN** the late-sorting subject is visited and eligible work is published without draining the early backlog first

#### Scenario: Locked and backing-off heads do not monopolize scans

- **GIVEN** one subject is locked and another has a backing-off head followed by due rows
- **WHEN** a worker completes a scan cycle
- **THEN** another eligible unlocked subject is served, neither unavailable subject monopolizes scanning, and the backed-off head is not bypassed

#### Scenario: Restart preserves pending work

- **GIVEN** a worker has advanced its scan and some publications are durably recorded
- **WHEN** the worker restarts with reset ephemeral scheduling state
- **THEN** pending work remains available, already completed rows are not treated as pending, and the new scan satisfies the finite-cycle fairness contract

#### Scenario: Synthetic load receipt measures the finite scan bound

- **GIVEN** a synthetic backlog with a recorded finite count N of candidate subjects, a positive subject examination budget B per pass, bounded rows per subject, and a continuously eligible unlocked target
- **WHEN** successive passes execute one complete scan with no change to the candidate set, using at least two workers in the load fixture
- **THEN** the target is visited within at most ceil(N / B) candidate-examination passes for a worker completing that scan; the receipt records N, B, per-subject row budget, observed passes, publish counts, backlog drain behavior and query timing, without claiming a wall-clock bound under unbounded arrivals

### Requirement: Publication uses current state under subject ownership

A relay SHALL recheck a subject's current pending delivery state after acquiring exclusive subject ownership. Concurrent workers SHALL NOT publish from a stale pre-ownership snapshot. Ambiguous transport outcomes SHALL retain at-least-once retry behavior with the original event id.

#### Scenario: Concurrent relays recheck completed rows

- **GIVEN** two workers identified the same subject and one publishes and records its head before the other gains ownership
- **WHEN** the second worker obtains ownership
- **THEN** it rechecks current pending state and does not publish the completed row from its old snapshot

#### Scenario: Poison head retains existing retry policy

- **GIVEN** a subject head repeatedly fails publication while independent subjects are ready
- **WHEN** five attempts with exponential backoff fail
- **THEN** the head is dead-lettered with depth at least one, unrelated service continues, and only manual runbook redrive can retry the dead-lettered row
