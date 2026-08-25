## Purpose

The baseline capability says how warehouse delivery behaves; this delta makes it exist. The
consumer becomes a provisioned workload on the tenant with the rule-and-queue transport the
baseline mandates, and its freshness becomes an observable fact rather than an assumption.

## ADDED Requirements

### Requirement: The warehouse consumer is a provisioned workload

The warehouse path SHALL exist as standing infrastructure: an EventBridge rule on the `ocean`
bus matching the ledger's published events, a dedicated SQS queue with a dead-letter queue,
the queue access policy admitting the rule, and the `warehouse-sync` consumer running as a
deployed service. The definitions SHALL be committed files applied by script, in the same
reviewable-shape posture as the relay's service definition.

#### Scenario: A committed ledger event lands as a warehouse row

- **GIVEN** the provisioned rule, queue, and running consumer
- **WHEN** a command commits and the relay publishes its envelope on the `ocean` bus
- **THEN** a row for that `event_id` appears in the raw events table, with `_topic` carrying
  the originating domain

#### Scenario: Redelivery still produces no second row

- **GIVEN** a row already landed for an `event_id`
- **WHEN** the same envelope is redelivered through the queue
- **THEN** the table gains no additional row for that `event_id`

### Requirement: Warehouse freshness is observable as one pinned query

The capability SHALL define a single freshness query — the age of the newest `_loaded_at` in
the raw events table — and the published contract SHALL carry it verbatim, so any consumer or
gate (including `survey-engine-ingress`'s entry metric) measures freshness the same way.

#### Scenario: The freshness figure is queryable after revival

- **GIVEN** the provisioned feed has processed at least one event
- **WHEN** the pinned freshness query runs
- **THEN** it returns the age in minutes of the newest landed row, and that age reflects the
  most recent committed ledger event rather than the pre-revival gap
