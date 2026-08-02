## Purpose

Defines the bus-side contract for publishing OCEAN events: how a former Kafka topic is addressed on
EventBridge, what the envelope looks like on the wire, and what a publisher must guarantee when the
bus rejects a write.

## ADDED Requirements

### Requirement: Topic addressing is a single generated mapping

Every former `ocean.<domain>` topic SHALL map to `source = "ocean"` and
`detail-type = "<domain>"`. Publishers and rule patterns SHALL both derive their values from one
generated mapping, so a rule cannot address a value no producer emits, or vice versa.

The mapping covers the eleven live domains: `signals`, `alerts`, `tasks`, `interactions`,
`outcomes`, `patient-state`, `tickets`, `ai-ops`, `audit`, `ops`, `logistics`.

#### Scenario: Every live topic has exactly one mapping entry

- **WHEN** the mapping is loaded
- **THEN** it contains one entry for each of the eleven live domains, and no entry for
  `warehouse-dlq`, which is retired

#### Scenario: Rule patterns match what publishers emit

- **GIVEN** the generated rule patterns and the generated publisher addressing
- **WHEN** both are compared against the mapping
- **THEN** every `detail-type` a rule matches is one some publisher can emit, and every
  `detail-type` a publisher can emit is matched by at least one rule

#### Scenario: An event type new to the catalog needs no rule change

- **GIVEN** the state catalog introduces a new `event_type` within an existing domain
- **WHEN** an event of that type is published
- **THEN** it is delivered by the existing rule for that domain, and no rule pattern is edited

### Requirement: The envelope is unchanged and travels whole

The event envelope SHALL cross the bus unmodified inside EventBridge `detail`. No envelope field
moves to `source`, `detail-type`, or any other EventBridge attribute. `event_type` remains an
envelope field.

#### Scenario: Envelope round-trips intact

- **WHEN** a publisher emits an envelope and a consumer receives the resulting message
- **THEN** the envelope the consumer parses is field-for-field identical to the one published

#### Scenario: event_type is not promoted to detail-type

- **WHEN** any event is published
- **THEN** its `detail-type` is the domain name, not its `event_type`

### Requirement: One shared publisher serves every publish site

All publish sites SHALL emit through one shared publisher rather than a per-service
implementation. No service retains its own transport-level publish code.

#### Scenario: No service-local transport code survives

- **WHEN** the migration completes
- **THEN** no source file outside the shared publisher library references a bus client directly

#### Scenario: Both former publisher shapes converge

- **GIVEN** the six keyed connector publishers and the six unkeyed publishers
- **WHEN** the migration completes
- **THEN** all twelve, plus the inline publish site in `warehouse-sync`, call the shared publisher

### Requirement: Publish failure falls back to a durable local queue

When the bus rejects or fails a publish, the publisher SHALL write the event to the Postgres
`failed_webhooks` table rather than dropping it. This fallback covers publish-side failure, which
no bus-side dead-letter queue can observe.

Every publish site SHALL have this fallback, including the six that had none under Kafka.

#### Scenario: Bus rejection is captured

- **GIVEN** the bus is unavailable or rejects the write
- **WHEN** a publish is attempted
- **THEN** the event is written to `failed_webhooks` and the failure is logged, and the caller does
  not raise

#### Scenario: Formerly unprotected publishers gain the fallback

- **GIVEN** a publish site that had no dead-letter fallback under Kafka
- **WHEN** its publish fails after the migration
- **THEN** the event is written to `failed_webhooks`

### Requirement: The grouping key survives the transport change

The publisher SHALL continue to accept a key and carry it as an envelope field. The key no longer
selects a partition; it is the value that consumer-side sequence guards group by.

#### Scenario: Key is carried, not dropped

- **WHEN** a publisher supplies a key
- **THEN** the key is present in the envelope the consumer receives

#### Scenario: Key is not used for routing

- **WHEN** two events with different keys and the same domain are published
- **THEN** both are delivered by the same rule to the same queues
