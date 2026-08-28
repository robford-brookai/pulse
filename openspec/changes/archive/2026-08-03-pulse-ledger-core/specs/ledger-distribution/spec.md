## Purpose

Defines how committed ledger events reach the EventBridge backbone: a transactional outbox with
per-subject ordering, at-least-once relay, and dead-lettering with a monitor — the record feeding
the existing distribution layer, never the other way around.

## ADDED Requirements

### Requirement: Committed events enter a transactional outbox

Every committed event SHALL be written to an outbox in the same transaction as the event, with a
per-subject sequence number. An event SHALL never be published that is not committed, and SHALL
never be silently dropped (D17).

#### Scenario: No publish without commit

- **WHEN** a command's transaction rolls back
- **THEN** no outbox row exists for it and nothing reaches the bus

### Requirement: Relay is at-least-once with per-subject ordering

The relay SHALL deliver outbox rows to the EventBridge bus at least once, in per-subject sequence
order; cross-subject ordering is not guaranteed. Consumers dedupe on `event_id` per the
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
- **THEN** the subject's events reach the bus in sequence order 1, 2, 3

### Requirement: Exhausted retries dead-letter loudly

A row failing 5 delivery attempts with exponential backoff SHALL move to a DLQ monitored at
depth ≥ 1; redrive SHALL be a manual, runbook-driven operator action, never automatic.

The DLQ is the outbox itself, marked `dead_lettered_at` in place, rather than a second table. A move
would duplicate the event id, subject, `seq`, attempt count, and the foreign key to `ledger.events`;
marking makes depth a count over one partial index and redrive a single UPDATE. Every observable
behaviour this requirement asks for is unchanged. The two monitored numbers are `dead_letter_depth()`
and `outbox_lag_seconds()`; both exist and are tested, and nothing scrapes them yet — wiring the
alarms belongs with 4.5's stack or S1 runtime readiness.

#### Scenario: Poison row alarms instead of blocking

- **GIVEN** an outbox row that fails 5 publish attempts
- **WHEN** the fifth attempt fails
- **THEN** the row lands in the DLQ, the monitor fires, and relay of other subjects continues
