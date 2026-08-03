# warehouse event sync Specification

## Purpose

Defines how events continue to reach Snowflake once the Redpanda Connect sink is removed, and what
happens to an event the warehouse cannot accept.

## Requirements

### Requirement: Events reach the warehouse without Redpanda Connect

Events SHALL continue to land in the Snowflake raw events table after the Redpanda Connect sink is
removed. Delivery SHALL use the same rule-and-queue mechanism as every other consumer, so the
warehouse path has no bespoke transport.

#### Scenario: Published events land in the warehouse

- **GIVEN** the Redpanda Connect sink is removed
- **WHEN** events are published
- **THEN** they appear in the Snowflake raw events table with their originating domain recorded

#### Scenario: No separate transport for the warehouse

- **WHEN** the warehouse path is inspected
- **THEN** it consumes from its own queue like every other consumer, with no additional streaming
  or staging service

### Requirement: The warehouse-dlq topic is retired

The dedicated `ocean.warehouse-dlq` topic SHALL be removed. Its role is taken by the warehouse
consumer's own dead-letter queue, so all dead-lettering is uniform across consumers.

#### Scenario: The dedicated topic no longer exists

- **WHEN** the topology is inspected after migration
- **THEN** no `warehouse-dlq` topic or equivalent bespoke dead-letter destination exists

#### Scenario: Warehouse failures dead-letter uniformly

- **GIVEN** an event the warehouse repeatedly fails to accept
- **WHEN** the redrive threshold is reached
- **THEN** the event lands in the warehouse consumer's dead-letter queue, observable the same way as
  any other consumer's

### Requirement: Warehouse delivery is order-tolerant and duplicate-safe

The warehouse path appends raw events. It SHALL reach the same table contents regardless of
delivery order, and a redelivered event SHALL NOT produce a duplicate row.

#### Scenario: Out-of-order delivery is immaterial

- **GIVEN** a set of events delivered in reverse order
- **WHEN** they are written to the warehouse
- **THEN** the table contents match those from in-order delivery

#### Scenario: Redelivery does not duplicate

- **GIVEN** an event already written
- **WHEN** the same event is redelivered
- **THEN** no additional row is created
