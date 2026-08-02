## Purpose

Defines what the local development stack must provide once Redpanda is removed, so that a
simulation run against a developer's machine exercises the same topology and reaches the same state
as a run against AWS.

## ADDED Requirements

### Requirement: Local dev provides the bus topology without Kafka

The local stack SHALL provide a bus, rules, and queues equivalent to the deployed topology, and
SHALL NOT run any Kafka or Redpanda component.

#### Scenario: No Kafka container remains

- **WHEN** the local stack is brought up
- **THEN** no `redpanda`, `redpanda-console`, or `redpanda-init` container starts

#### Scenario: A developer can run the full event path locally

- **GIVEN** a freshly brought-up local stack
- **WHEN** an event is published
- **THEN** it reaches every subscribing consumer without any AWS account being involved

### Requirement: Local and deployed topology derive from one source

The local bus, rules, and queues SHALL be created from the same mapping that generates the deployed
rule patterns and publisher addressing. Local topology SHALL NOT be maintained separately.

#### Scenario: Adding a domain updates both

- **GIVEN** a new domain added to the mapping
- **WHEN** the local stack is recreated and the deployed topology is applied
- **THEN** both carry the new domain with no additional edit

#### Scenario: Local setup is idempotent

- **WHEN** the local topology creation runs against a stack where it has already run
- **THEN** it succeeds and leaves the topology unchanged

### Requirement: Simulation reaches identical state on either transport

Running the two existing simulators against the local stack SHALL leave every consumer's stored
state indistinguishable from the state the same run produces on the Kafka path today. This
equivalence is the regression net for the consumer rewrite and a precondition of retiring the
deployed Kafka infrastructure.

#### Scenario: Graph tables match

- **GIVEN** a simulation run on the Kafka path and the same run on the local stack
- **WHEN** the resulting graph tables are compared
- **THEN** they are equivalent, ignoring only values that are wall-clock or identifier-random by
  construction

#### Scenario: Audit log matches

- **GIVEN** the same two runs
- **WHEN** the resulting `audit_log` contents are compared
- **THEN** the same events are recorded, with the same identifiers

#### Scenario: Equivalence gates the teardown

- **GIVEN** the equivalence comparison has not passed
- **WHEN** teardown of the deployed Kafka infrastructure is proposed
- **THEN** it is blocked

### Requirement: Local fidelity limits are covered by assertion elsewhere

The local stack validates wiring and consumer logic, not access control, service quotas, or
delivery-latency behavior. Rule-pattern correctness SHALL additionally be asserted directly against
the mapping, so that a local-emulator quirk cannot mask a wrong pattern.

#### Scenario: Rule patterns are asserted without the emulator

- **WHEN** the test suite runs
- **THEN** every generated rule pattern is checked against the mapping without requiring the local
  stack to be running
