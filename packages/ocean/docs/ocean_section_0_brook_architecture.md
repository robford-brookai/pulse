# 0. OCEAN: Realistic Production Architecture for Brook

**OCEAN** is an event-driven operational platform for Brook:

- **O**perational Control Plane (routing + rules + human approvals)
- **E**vent Backbone (durable event transport)
- (Operational) d**A**ta Graph (the operational object model + relationships)
- (AI) k**N**owledge Layer (summaries + recommendations + institutional memory)
Given Brook’s constraints — ~170 employees (35 care staff, 15 engineers), **Slack as the operational UI**, Zoom Contact Center (ZCC) for calling, HIPAA/PHI requirements, and a ~5‑engineer implementation team — the most realistic architecture is **not** a large microservices platform.

The architecture that works at this scale is a **thin event backbone + operational data graph + Slack control plane**: an **operations nervous system layered on top of existing systems**, rather than replacing them.

## Problem Context

Brook generates roughly:

- ~30 support tickets/day
- ~200 care alerts/day (≈70% false positives, 25% routine, 5% urgent)
- ~15 engineering issues/day
- ~50 operational Slack messages/day
Departmental systems are intentionally specialized:

| Department | Tools |
|---|---|
| Engineering | Linear, GitHub, Slack |
| Marketing | Slack, HubSpot, Customer.io |
| Care Operations | POCAR |
| Patient Operations | PAP, ex-dash |
| Data Platform | Snowflake, dbt |

The resulting friction is predictable:

- **System silos:** cross-team work defaults to Slack messages and manual ticket creation.
- **Fragmented knowledge:** decisions and context are scattered across Slack threads, ticket histories, PRs, care system logs, and warehouse queries.
- **Care alert noise:** high false positives create an urgent need for triage, automation, and outcome-based learning.
## Guiding Principles

1. **Do not replace existing systems.** Wrap them with events.
2. **Slack is the operational UI.**
3. **Events are facts; tasks are derived.** (The control plane turns facts into work.)
4. **AI assists but humans act.**
5. **Build the operational graph first, not dashboards.**
## Why Events (Not a Service Bus + Headless Ticketing)

An early “service bus + unified ticketing” approach looks attractive, but it tends to fail for three reasons:

- **Semantic drift:** forcing support tickets, engineering issues, and care escalations into one abstraction creates ambiguity.
- **Integration fragility:** adapter sprawl and tight coupling make the bus brittle.
- **Ownership conflict:** a central ticketing system becomes a shadow system that departments route around.
OCEAN exchanges **events** — immutable facts that occurred — rather than trying to standardize all work into a single ticket model.

## System Overview (OCEAN Layers)

```text
External Systems
  (EHR via Citrix, RPM platforms, messaging, Zoom Contact Center,
   Linear, GitHub, Slack, HubSpot, POCAR, PAP/ex-dash, etc.)
        │
        ▼
Event Intake Layer
  (webhooks + API polling + normalizers)
        │
        ▼
Event Backbone
  (Kafka-compatible, e.g. Redpanda; or NATS JetStream as an alternative)
        │
        ├──────────────► Data Warehouse (Snowflake + dbt)
        │
        ▼
Operational Event Store + Operational Data Graph
  (Postgres + graph projection / GraphQL)
        │
        ▼
Operational Control Plane
  (rules + task routing + approvals)
        │
        ▼
AI Knowledge Layer
  (summaries + recommendations)
        │
        ▼
Slack Bot / Slack Threads (operational command UI)
        │
        ▼
Human Action (care team) ──► Call patient (ZCC)
        │
        ▼
Outcome Events Logged ──► Learning Loop
```

## HIPAA-Safe Event Model

Events must not carry PHI. The event model enforces:

1. **No PHI in events:** events contain identifiers + metadata only.
2. **Reference linking:** protected systems retrieve PHI on-demand using `patient_id`, `alert_id`, `ticket_id`, etc.
3. **Full audit trail:** every event records actor, timestamp, source system, and workflow/correlation IDs.
## Core Infrastructure (Simple + Realistic)

| Layer | Technology |
|---|---|
| Event intake | FastAPI services (connectors/normalizers) |
| Event backbone | Redpanda (Kafka-compatible) or NATS JetStream |
| Operational database | Postgres |
| Graph API | Hasura or GraphQL service |
| AI layer | OpenAI / Anthropic |
| Data warehouse | Snowflake |
| Analytics transforms | dbt |
| Operational UI | Slack |

This can be delivered as a handful of deployable services (**~6–9**), which is realistic for a five‑engineer team.

## Core Operational Entities (Operational Graph)

These entities power the operational system:

- Patient
- Clinic
- CareTeamMember
- Signal
- Alert
- Task
- Interaction
- Outcome
Example operational chain:

```text
Patient
  └─ Alert
      └─ Task (call patient)
          └─ Interaction (phone call)
              └─ Outcome
```

## Event Taxonomy (Minimal)

A minimal event taxonomy keeps the system manageable:

- `patient.created`
- `patient.updated`
- `alert.created`
- `alert.triaged`
- `alert.resolved`
- `task.created`
- `task.assigned`
- `task.completed`
- `call.started`
- `call.connected`
- `call.completed`
- `call.missed`
- `ai.summary.generated`
- `ai.recommendation.generated`
Small taxonomy = easier operations.

See Section 1 for the full canonical taxonomy and the event envelope standard.

## AI Layer (Practical)

AI is assistive (summaries, recommendations, drafts) and **never executes clinical actions autonomously**.

See Section 5 for safety boundaries, context retrieval (RAG), and audit events.

## Slack Operational UI

Slack is the operational control interface: events surface as threads, and humans claim/complete tasks in place.

See Section 4 for control plane + Slack workflow details and examples.

## Key Integrations

### Zoom Contact Center (ZCC)

Ingest **call lifecycle events** and attach them to the patient interaction graph.

Example event types:

- `call.started`
- `call.connected`
- `call.completed`
- `call.missed`
### Departmental Systems

Department tools (Linear/GitHub, HubSpot/Customer.io, POCAR, PAP/ex-dash, etc.) should be integrated by emitting domain events rather than forcing a single “ticket” schema.

## Citrix / EHR Constraint

Because the care team accesses EHR systems via Citrix, those systems remain **human-operated systems**.

However, **actions taken there should generate events** where possible (initially manual; automated later):

- `patient_medication_changed`
- `visit_scheduled`
- `note_added`
## Minimal Service Architecture

A realistic deployable system (exact boundaries can vary; see Section 6):

1. `event-ingestion-service`
2. `event-backbone`
3. `event-store`
4. `graph-projection`
5. `graph-api`
6. `control-plane`
7. `slack-bot`
8. `ai-assist` (optional)
9. `warehouse-sync` (optional)
## Implementation Phases (Progressive)

Introduce the architecture through capability phases (not strict timelines):

### Phase 1 — Event Backbone

Goal: capture operational events.

Build:

- ingestion + normalization
- event schema + validation
- durable event backbone + event store
Sources include RPM alerts, patient messages, ZCC call events, and Slack actions.

Outcome: **all operations become events**.

### Phase 2 — Operational Data Graph

Build core entities: patients, alerts, tasks, interactions.

This enables questions like:

- Which alerts caused calls?
- Which calls resolved alerts?
### Phase 3 — Slack Control Plane

Add task routing, task claiming, and task completion.

Slack becomes the **operations console**.

### Phase 4 — AI Assist

Add alert summarization, patient response drafts, and triage suggestions.

Humans remain in control.

### Phase 5 — Learning Loop

Use outcomes to improve thresholds, AI recommendations, and clinic workflow rules.

This is how the system reduces the **70% false positive alert rate**.

## What This Architecture Achieves

Instead of:

> alerts → operational chaos

You create a system where:

> signals → tasks → actions → outcomes → learning

## The Real Risk

The hardest part of the architecture is **not the technology**.

The difficult problems are:

- defining the event schema
- designing the operational task model
- encoding workflow rules
## One Strategic Insight

Brook is effectively building a **remote care operating system**.

Several large technology companies eventually developed internal systems based on similar principles of event-driven operational infrastructure (Stripe, Airbnb, Uber, Amazon).

OCEAN is the same class of system: an event-driven operational platform designed to coordinate complex human and software workflows.
