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

#### Scenario: Poison row alarms instead of blocking

- **GIVEN** an outbox row that fails 5 publish attempts
- **WHEN** the fifth attempt fails
- **THEN** the row lands in the DLQ, the monitor fires, and relay of other subjects continues
