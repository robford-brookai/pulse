# 6. Implementation Blueprint

## Purpose

This section translates the OCEAN architecture into a realistic implementation blueprint for a ~5‑engineer team.

The goal is not to build a large distributed system, but to incrementally create a **care operations nervous system** layered on top of existing Brook tools.

The implementation strategy follows several principles:

- introduce infrastructure gradually
- prioritize operational visibility early
- avoid premature microservices
- keep the architecture operable by a small team
- deliver incremental value to care teams
The system should evolve through capability layers, not large rewrites.

---

## Implementation Strategy

OCEAN should be implemented in five progressive layers:

1. Event Backbone
2. Operational Event Store
3. Operational Data Graph
4. Control Plane
5. AI Assist Layer
Each layer builds on the previous one while remaining deployable.

---

## System Components

The initial production architecture should include the following services.

```text
event-ingestion-service
event-backbone
event-store
graph-projection
graph-api
control-plane
slack-bot
ai-assist-service
warehouse-sync
```

Not all components must be deployed simultaneously.

---

## Service Overview

### Event Ingestion Service

Purpose:

Convert external system activity into **OCEAN events**.

Responsibilities:

- consume webhooks
- poll APIs when necessary
- normalize events into canonical schema
- publish events to backbone
Sources include:

- RPM alert systems
- patient messaging systems
- Zoom Contact Center
- internal Slack actions
- internal operational tools
Suggested stack:

```text
FastAPI
Python
Redpanda (Kafka producer)
```

---

### Event Backbone

The backbone distributes events across the platform.

Requirements:

- durable message queue
- ordered event streams
- consumer subscriptions
- event replay capability
Recommended technologies:

```text
Redpanda (Kafka-compatible)
```

This layer ensures that **every operational event becomes observable and replayable**.

---

### Operational Event Store

The event store persists the event stream.

Recommended storage:

```text
Postgres
```

Schema example:

```text
events
- event_id
- event_type
- entity_type
- entity_id
- timestamp
- payload
```

The event store supports:

- debugging
- operational auditing
- event replay
- graph projections
---

### Graph Projection Service

The projection service converts events into **Operational Data Graph state**.

Responsibilities:

- listen to event streams
- update graph tables
- maintain entity relationships
Example transformations:

```text
alert.created → create Alert node
task.created → create Task node
call.completed → create Interaction node
```

Suggested stack:

```text
Python worker
Kafka consumer
Postgres writes
```

---

### Graph API Layer

The Graph API exposes operational state to applications.

Recommended approach:

```text
GraphQL API
```

Benefits:

- flexible queries
- client-driven data fetching
- easy integration with Slack apps and dashboards
Technology options:

```text
Hasura
or a thin GraphQL service
```

---

### Control Plane Service

The Control Plane coordinates workflows.

Responsibilities:

- rule evaluation
- task generation
- escalation logic
- operational policy enforcement
Example rule:

```text
IF alert.created
AND alert.type = glucose_missing

THEN create task(call_patient)
```

Implementation options:

```text
Python rule engine (recommended for v1)
Temporal workflows (later)
```

For an early system, **a simple rule engine is sufficient**.

---

### Slack Bot Interface

Slack acts as the **operational user interface**.

Capabilities include:

- alert notifications
- task claiming
- workflow approvals
- operational context display
Example Slack workflow:

```text
Alert posted
→ nurse clicks Claim Task
→ task.claimed event generated
→ workflow progresses
```

Recommended stack:

```text
Slack Bolt framework
Python or Node.js
```

---

### AI Assist Service

The AI Assist Service provides operational copilots.

Responsibilities:

- build prompts
- retrieve operational context
- call LLM APIs
- record AI events
- format outputs for Slack
Architecture:

```text
Context retrieval
→ prompt construction
→ LLM API
→ output formatting
```

The service should be **stateless** and easily replaceable.

---

### Warehouse Sync Service

Operational data should flow into the analytics warehouse.

Pipeline:

```text
Event backbone
→ export/ELT
→ Snowflake
→ dbt transformations
```

The warehouse enables:

- operational analytics
- model training
- alert optimization
- reporting
---

## Recommended Technology Stack

A minimal but production-ready stack:

```text
Language: Python
API framework: FastAPI
Messaging: Redpanda (Kafka-compatible)
Operational database: Postgres
Graph API: GraphQL
Workflow engine: simple rules engine
AI provider: OpenAI / Anthropic
Warehouse: Snowflake
Transformations: dbt
Interface: Slack
```

This stack balances:

- simplicity
- maintainability
- scalability
---

## Repository Structure

A clean monorepo structure helps a small team move quickly.

Example layout:

```text
ocean/
  services/
    event-ingestion/
    event-store/
    graph-projection/
    control-plane/
    slack-bot/
  libs/
    ocean-events/
  infra/
  docs/
```

Shared libraries prevent duplication across services.

---

## Deployment Model

Early deployments should prioritize **simplicity over sophistication**.

Initial deployment approach:

```text
Docker containers
single cloud cluster
managed Postgres
managed Redpanda/Kafka
```

Cloud providers may include:

- AWS
- GCP
- Azure
Container orchestration can start with:

```text
Docker Compose
```

and later move to:

```text
Kubernetes
```

if operational scale requires it.

---

## Observability

Operational systems must include strong observability.

Core monitoring includes:

- event throughput
- task queue depth
- alert resolution times
- system errors
Recommended tooling:

```text
Prometheus
Grafana
OpenTelemetry
```

Logging should capture:

- event ingestion
- rule execution
- AI outputs
- workflow transitions
---

## Security Requirements

Because Brook handles PHI, the system must enforce:

- encrypted transport (TLS)
- role-based access control
- secure API authentication
- audit logging
- data encryption at rest
Operational access should be restricted by role.

Example roles:

```
nurse
support
analyst
admin
```

---

## Minimal Viable System

A functional Ocean MVP could consist of only:

```text
event-ingestion-service
event-backbone
event-store
control-plane
slack-bot
```

This minimal system already enables:

- alert routing
- task assignment
- operational visibility
The graph and AI layers can be added later.

---

## Long-Term Evolution

As the system matures, additional capabilities may include:

- predictive alert filtering
- automated workflow optimization
- clinic-specific rule engines
- operational simulation tools
- advanced AI copilots
However, these should be introduced **only after the core event architecture stabilizes**.

---

## Key Implementation Principle

The most important rule of the implementation blueprint is:

**Build operational visibility before automation.**

When every signal, alert, task, and interaction becomes an event, the organization gains the data needed to improve care operations safely and intelligently.
