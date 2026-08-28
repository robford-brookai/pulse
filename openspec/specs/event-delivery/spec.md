# event delivery Specification

## Purpose

Defines the consumer-side contract after Kafka is retired: how events reach each consumer, what
each consumer must guarantee about duplicate and out-of-order delivery, and how undeliverable
events are retained and replayed.

## Requirements

### Requirement: Each consumer has a dedicated rule and queue

Each of the seven consumers SHALL receive events through one rule matching its own set of
`detail-type` values, targeting one queue dedicated to that consumer. No consumer SHALL receive
events it does not subscribe to.

#### Scenario: A consumer receives only its own domains

- **GIVEN** a consumer subscribed to a subset of domains
- **WHEN** an event outside that subset is published
- **THEN** it does not appear on that consumer's queue

#### Scenario: Fan-out to multiple consumers is preserved

- **GIVEN** a domain that more than one consumer subscribes to
- **WHEN** an event in that domain is published
- **THEN** every subscribing consumer receives its own copy

#### Scenario: Competing consumers within a service still share work

- **GIVEN** more than one poller running for the same consumer
- **WHEN** events arrive
- **THEN** each event is processed by exactly one poller under normal operation

### Requirement: Processing completes before acknowledgement

A consumer SHALL delete a message only after processing it successfully. A failed message SHALL be
left for redelivery. This preserves the at-least-once, commit-after-success semantics the Kafka
consumers had.

#### Scenario: Failure redelivers

- **GIVEN** a consumer that raises while processing a message
- **WHEN** the failure occurs
- **THEN** the message is not deleted, and it is redelivered

#### Scenario: Success acknowledges

- **GIVEN** a consumer that processes a message without error
- **WHEN** processing returns
- **THEN** the message is deleted and is not redelivered

### Requirement: Every consumer has a recorded ordering verdict

Delivery is unordered. Before a consumer is converted, it SHALL carry a recorded verdict of
**order-tolerant** or **order-dependent**, justified by evidence in its code rather than by
assumption.

An order-tolerant consumer SHALL reach the same final state regardless of delivery order. An
order-dependent consumer SHALL be given a sequence guard that makes it so.

#### Scenario: No consumer is converted without a verdict

- **WHEN** a consumer conversion is reviewed
- **THEN** its verdict is recorded with the evidence supporting it

#### Scenario: Out-of-order delivery reaches the same state

- **GIVEN** a set of events for one entity
- **WHEN** they are delivered in reverse order to a converted consumer
- **THEN** the resulting stored state is identical to the state after in-order delivery

### Requirement: Sequence guards compare event time, never processing time

A sequence guard SHALL compare a field whose value is fixed when the event is produced. A guard
SHALL NOT compare a value assigned when the event is processed, because under reordering such a
value encodes arrival order and re-encodes the bug the guard exists to fix.

#### Scenario: A processing-time guard is rejected

- **GIVEN** a candidate guard comparing a column populated with the processing timestamp
- **WHEN** the conversion is reviewed
- **THEN** it is rejected

#### Scenario: A terminal state is not overwritten by an earlier event

- **GIVEN** an entity whose state was set by a later event
- **WHEN** an earlier event for that entity arrives afterwards
- **THEN** the stored state is unchanged

### Requirement: Deduplication does not satisfy the ordering requirement

A predicate that suppresses re-processing of the same event SHALL NOT be accepted as a sequence
guard. Such a predicate prevents a duplicate; it does not prevent an older event from overwriting
a newer one.

#### Scenario: A dedup-only predicate is treated as unguarded

- **GIVEN** an upsert guarded only by a comparison against the last processed event identifier
- **WHEN** its consumer's ordering verdict is assessed
- **THEN** the site counts as unguarded and requires a sequence guard

#### Scenario: A distinct earlier event still overwrites without a guard

- **GIVEN** an upsert guarded only against repeat of the same event
- **WHEN** a different, earlier event for the same entity arrives after a newer one
- **THEN** without a sequence guard the earlier event overwrites — this is the condition the guard
  must eliminate

### Requirement: External side effects are skipped, not replayed, when stale

A consumer whose effect leaves the system — posting or updating an external message — SHALL drop a
stale update rather than apply it. A later-arriving older event SHALL NOT overwrite a newer
external state.

#### Scenario: A stale external update is dropped

- **GIVEN** an external message already updated by a later event
- **WHEN** an earlier event for the same entity is processed
- **THEN** no external update is issued and the event is acknowledged

#### Scenario: The terminal external state matches in-order delivery

- **GIVEN** an entity lifecycle delivered out of order
- **WHEN** all its events have been processed
- **THEN** the external message shows the state it would show under in-order delivery

### Requirement: Undeliverable events are retained per queue

Each queue SHALL have a dead-letter queue and a redrive policy. An event that cannot be processed
after the configured attempts SHALL land in that consumer's dead-letter queue rather than being
discarded or retried indefinitely.

#### Scenario: Repeated failure dead-letters

- **GIVEN** a message that fails on every attempt
- **WHEN** the redrive threshold is reached
- **THEN** the message is moved to that consumer's dead-letter queue

#### Scenario: Dead-letter volume is observable

- **WHEN** a message lands in a dead-letter queue
- **THEN** it is visible to monitoring, per consumer

### Requirement: A bounded archive supports convenience replay

The bus SHALL retain an archive from which events can be replayed to re-drive a consumer that
missed a window. Replay SHALL be permitted only where the consumer's idempotency makes the result
identical to not having missed the window.

The archive is not the record. The durable record remains the append-only `audit_log`.

#### Scenario: A consumer is re-driven from the archive

- **GIVEN** a consumer that missed a window of events within the retention period
- **WHEN** that window is replayed
- **THEN** the consumer reaches the state it would have reached without the gap

#### Scenario: The archive is not treated as authoritative

- **WHEN** an authoritative rebuild is required
- **THEN** it reads the durable record, not the archive
