# OCEAN Technical Reference
 
This is the implementation reference for the OCEAN architecture. It covers event schemas, the operational object model, the data graph, the control plane, AI-assisted operations, implementation blueprint, and production operations.
 
For the leadership case — problem, pilot justification, roadmap, governance, and success metrics — see the [Leadership Proposal](./ocean_leadership_proposal.md).
 
---
 
## Architectural Baseline
 
OCEAN is a thin event backbone + operational data graph + Slack control plane, layered on top of Brook's existing departmental systems. It consists of ~6–9 deployable services, realistic for a five-engineer team.
 
### Core Infrastructure
 
| Layer | Technology |
|---|---|
| Event intake | FastAPI services (connectors/normalizers) |
| Event backbone | Redpanda (Kafka-compatible) or NATS JetStream |
| Operational database | Postgres |
| Graph API | Hasura or GraphQL service |
| AI layer | OpenAI / Anthropic |
| Data warehouse | Snowflake |
| Analytics transforms | dbt |
| Operational UI | Slack (Bolt framework) |
 
### Design Priorities
 
When making implementation tradeoffs, apply this hierarchy:
 
1. **Slack-first workflows** — if it doesn't work in Slack, it doesn't work.
2. **Event capture before automation** — without the event layer, automation is guesswork.
3. **Visibility before orchestration** — observe the system before optimizing it.
4. **Assistive AI before autonomous AI** — summarize and recommend before orchestrating.
### System Flow
 
```text
External Systems
  (EHR via Citrix, Impilo, ZCC, Linear, GitHub, Slack, HubSpot, POCAR, PAP/ex-dash)
        │
        ▼
Event Intake Layer (webhooks + API polling + normalizers)
        │
        ▼
Event Backbone (Redpanda)
        │
        ├──► Data Warehouse (Snowflake + dbt)
        │
        ▼
Event Store + Operational Data Graph (Postgres + GraphQL)
        │
        ▼
Control Plane (rules + task routing + approvals)
        │
        ▼
AI Knowledge Layer (summaries + recommendations)
        │
        ▼
Slack Bot (operational command UI)
        │
        ▼
Human Action ──► Call patient (ZCC) ──► Outcome Events ──► Learning Loop
```
 
### HIPAA-Safe Event Model
 
This applies to all sections of this document. Events carry identifiers and metadata only — no PHI. Protected systems retrieve patient data on demand using reference IDs (`patient_id`, `alert_id`, etc.). Every event records actor, timestamp, source system, and workflow/correlation IDs for audit.
 
Services that access PHI must enforce encryption in transit and at rest, least-privilege RBAC, audit logging, and BAA coverage for third-party providers (including LLM APIs).
 
---
 
## 1. Event Taxonomy
 
### Purpose
 
The event taxonomy defines the canonical operational events across Brook. Events are the shared language of operations — loose coupling, real-time awareness, workflow automation, AI grounding, and auditability all depend on a stable taxonomy.
 
### Event Design Principles
 
**Events represent facts.** Events describe something that already happened. They are not commands.
 
- `alert.created` — yes
- `create_alert` — no
**Events are immutable.** Append-only. Prefer `alert.status_changed` over `alert.updated`.
 
**Events are contextual.** Every event includes at minimum: `entity_id`, `timestamp`, `actor`, `source_system`.
 
### Event Envelope Standard
 
All events share a common envelope:
 
```json
{
  "event_id": "evt_123",
  "event_type": "alert.created",
  "timestamp": "ISO8601",
  "source_system": "impilo",
  "entity_id": "alert_456",
  "entity_type": "alert",
  "correlation_id": "wf_789",
  "payload": {}
}
```
 
### Event Categories
 
The taxonomy covers six domains.
 
#### 1) Patient Lifecycle
 
| Event | Description |
|---|---|
| `patient.created` | Patient record created |
| `patient.updated` | Demographic or metadata updated |
| `patient.enrolled` | Enrolled in program |
| `patient.unenrolled` | Removed from program |
| `patient.consent_recorded` | Consent captured |
| `patient.consent_revoked` | Consent withdrawn |
 
#### 2) Clinical Signals
 
Signals are raw incoming patient data, not yet alerts. Sources: Impilo devices, surveys, messages, missing measurements.
 
| Event | Description |
|---|---|
| `signal.received` | Incoming clinical measurement |
| `signal.missing` | Expected signal not received |
| `signal.anomalous` | Signal outside expected range |
 
Example payload:
 
```json
{
  "event_type": "signal.received",
  "patient_id": "pt_84723",
  "signal_type": "glucose_reading",
  "value": 195,
  "unit": "mg/dL"
}
```
 
#### 3) Alerts
 
Triaged clinical signals requiring review.
 
| Event | Description |
|---|---|
| `alert.created` | Alert generated |
| `alert.triaged` | Nurse or AI triaged alert |
| `alert.escalated` | Alert escalated |
| `alert.resolved` | Alert resolved |
| `alert.dismissed` | False positive |
 
Capturing `alert.dismissed` is essential for the learning loop.
 
#### 4) Tasks
 
Human work assignments.
 
| Event | Description |
|---|---|
| `task.created` | Work item generated |
| `task.assigned` | Task assigned to staff |
| `task.claimed` | Worker claimed task |
| `task.started` | Work began |
| `task.completed` | Task finished |
| `task.canceled` | Task no longer required |
 
#### 5) Interactions
 
Communication with patients. Integrates with Zoom Contact Center.
 
| Event | Description |
|---|---|
| `call.started` | Phone call initiated |
| `call.connected` | Call answered |
| `call.completed` | Call finished |
| `call.missed` | Patient did not answer |
| `message.sent` | Message sent to patient |
| `message.received` | Message received from patient |
 
#### 6) AI Operations
 
AI activity must be recorded for safety and auditability.
 
| Event | Description |
|---|---|
| `ai.summary.generated` | Alert summary created |
| `ai.recommendation.generated` | Suggested action generated |
| `ai.response.drafted` | Patient message drafted |
| `ai.feedback.recorded` | Human accepted/rejected output |
| `ai.output.approved` | Human approved AI output |
| `ai.output.rejected` | Human rejected AI output |
 
### End-to-End Event Flow
 
Patient misses a glucose reading:
 
```text
signal.missing
→ alert.created
→ ai.summary.generated
→ ai.recommendation.generated
→ task.created
→ task.claimed
→ call.started
→ call.completed
→ alert.resolved
```
 
---
 
## 2. Operational Object Model
 
### Purpose
 
The object model defines the canonical entities OCEAN uses to represent operational state. The event taxonomy (Section 1) describes *what happened*; the object model defines *what exists*.
 
Design goals: support the care loop, integrate multiple systems without vendor lock-in, remain small enough for a five-engineer team.
 
Core philosophy: **few entities, many events.**
 
### Core Objects
 
| Object | What it represents |
|---|---|
| Patient | Central subject of care operations (`patient_id`) |
| Clinic | Partner organization and its policies/protocols |
| CareTeamMember | Staff member who performs operational work |
| Signal | Raw incoming patient telemetry (readings, missing readings, surveys, messages) |
| Alert | Triaged signal requiring review and potential action |
| Task | Human work item created by the control plane |
| Interaction | Communication with the patient (call, SMS, portal message, scheduling) |
| Outcome | Result of an interaction, used for learning and policy improvement |
 
### Object Layers
 
**Identity layer:** Patient, Clinic, CareTeamMember.
 
**Signal layer:** Signal (incoming data before triage).
 
**Work layer:** Alert (triaged signal), Task (assigned work item).
 
**Interaction layer:** Interaction (patient communication), Outcome (result).
 
### Attributes
 
#### Patient
 
- `patient_id`, `clinic_id`, `program_enrollment`, `consent_status`, `risk_profile`, `external_references`
#### Clinic
 
- `clinic_id`, `ehr_system`, `rpm_programs`, `clinical_rules_ref`
#### CareTeamMember
 
- `staff_id`, `role` (nurse, support, physician, analyst), `team`, `availability`, `permissions`
#### Signal
 
- `signal_id`, `patient_id`, `signal_type`, `value`, `timestamp`, `source_system`
#### Alert
 
- `alert_id`, `patient_id`, `signal_id` (optional), `alert_type`, `severity`, `status` (open, escalated, resolved, dismissed)
#### Task
 
- `task_id`, `patient_id`, `alert_id` (optional), `task_type`, `priority`, `status`, `assigned_staff_id` (optional)
#### Interaction
 
- `interaction_id`, `patient_id`, `interaction_type`, `start_time`, `end_time`, `status`
#### Outcome
 
- `outcome_id`, `interaction_id`, `outcome_type`, `resolution_status`, `notes_ref`
### Operational Lifecycle
 
```text
Patient → Signal → Alert → Task → Interaction → Outcome
```
 
### Design Principles
 
**Event-sourced state.** Objects are materialized views of events. `Task.status` is derived from `task.created`, `task.assigned`, `task.completed`.
 
**System-agnostic.** An `Interaction` represents calls regardless of whether they originate from ZCC, Twilio, or an EHR call log.
 
---
 
## 3. Operational Data Graph
 
### Purpose
 
The Operational Data Graph makes relationships between operational entities queryable. The event backbone records everything that happened; the graph answers *what is the current state and how are things connected?*
 
### Why a Graph Model
 
Care operations are relationship-driven. Common questions require traversing connected entities: Which alerts belong to this patient? Which tasks were generated by this alert? Which care team member completed the task? Which interactions resolved the alert?
 
The graph connects these into a continuous lifecycle rather than isolated tables.
 
### Nodes and Edges
 
Nodes correspond to the object model (Section 2).
 
Edges:
 
- Patient → has_signal → Signal
- Signal → triggered → Alert
- Alert → generated → Task
- Task → assigned_to → CareTeamMember
- Task → resolved_by → Interaction
- Interaction → produced → Outcome
- Outcome → affects → Patient
### Materialization: Events → Graph
 
Projection consumers listen to the event backbone and update graph state in Postgres.
 
```text
alert.created  → create Alert node
task.created   → create Task node + Alert → Task edge
call.completed → create Interaction node + Task → Interaction edge
```
 
The graph is a near-real-time projection of operational events.
 
### Storage
 
Postgres for operational queries (graph tables). Snowflake for analytical queries (via export/ELT + dbt). GraphQL API (Hasura or thin service) exposes the graph to applications.
 
### Query Patterns
 
**What requires action?** Open tasks of type `call_patient`, traversing Alert → Task → CareTeamMember.
 
**What happened to this patient recently?** Patient → Signals → Alerts → Tasks → Interactions → Outcomes (last 48 hours).
 
**Where is noise coming from?** Alerts where outcome.type = `false_positive`, aggregated by alert_type and clinic.
 
### AI Context Retrieval
 
The graph is the primary context source for AI operations (Section 5). Structured retrieval bundles (recent signals, alerts, open tasks, interactions, known outcomes) replace arbitrary text, reducing hallucination risk.
 
### Warehouse Synchronization
 
Operational graph data streams to Snowflake for cohort analysis and longitudinal reporting:
 
```text
Event Backbone → Postgres Graph → Export/ELT → Snowflake → dbt models
```
 
---
 
## 4. Operational Control Plane
 
### Purpose
 
The control plane turns facts (events) into work (tasks) while preserving human authority. It consumes events from the backbone, evaluates rules, and publishes new operational events (task creation, assignment, escalation, resolution).
 
### Inputs
 
```text
signal.received, signal.missing, alert.created, alert.escalated,
task.completed, call.completed, message.received, ai.recommendation.generated
```
 
### Outputs
 
```text
task.created, task.assigned, task.escalated, alert.resolved, alert.dismissed
```
 
### Rule Engine
 
Rules evaluate incoming events and create tasks.
 
Example:
 
```text
IF signal.missing
AND signal.type = glucose_reading
AND patient.enrolled_in = diabetes_program
 
THEN create alert
THEN create task(call_patient)
```
 
Rules encode clinic policies and care protocols into operational logic.
 
### Task Generation
 
Typical task types: `call_patient`, `review_alert`, `verify_device_usage`, `escalate_to_physician`, `send_patient_message`.
 
### Task Routing
 
Routing considers: care team role, clinic assignment, nurse availability, alert severity, workload balancing.
 
```text
IF task.type = call_patient
AND alert.severity = urgent
 
ROUTE TO on_call_nurse
```
 
### Slack as the Operational Interface
 
Slack is the human control surface. The control plane posts decisions to Slack and captures human actions.
 
Example Slack alert in `#care-alerts`:
 
```text
🚨 Care Alert
 
Patient: John Doe
Alert: Missing glucose readings
 
AI Summary:
Patient missed two readings today.
 
Recommended Action:
Call patient.
 
[Claim Task] [View Context]
```
 
Slack actions generate events: `task.claimed`, `task.completed`, `task.reassigned`.
 
When a call task is claimed, call lifecycle events (`call.started` → `call.connected` → `call.completed`) flow from ZCC back into the data graph.
 
### Escalation Logic
 
```text
IF alert.severity = urgent
AND task.not_completed_after = 30 minutes
 
THEN escalate_to_physician
```
 
```text
IF patient_unreachable
THEN create follow_up_task
```
 
### Human-in-the-Loop Governance
 
AI may suggest actions; execution requires human confirmation. See Section 5 for safety boundaries and audit requirements.
 
### Failure Isolation
 
- **Slack unavailable:** Tasks still created. Route urgent alerts via fallback notification (email/pager).
- **ZCC unavailable:** Keep tasks open. Allow manual call workflow; record outcomes afterward.
---
 
## 5. AI-Assisted Operations
 
### Purpose
 
AI is a copilot for care operations, not an autonomous decision-maker.
 
**AI recommends. Humans decide. Systems record.**
 
### Roles
 
**1) Alert Summarization.** Condense fragmented context (signals, missed measurements, patient messages, history) into a nurse-readable brief.
 
Example output:
 
```text
Summary:
Patient missed today's glucose reading after elevated reading yesterday.
Patient reported dizziness via message.
Recommend nurse follow-up call.
```
 
**2) Workflow Recommendations.** Suggest next actions based on operational context.
 
```text
Suggested actions:
- Call patient to verify device usage
- Review insulin instructions
```
 
Recommendations appear in Slack as decision support, not automation.
 
**3) Draft Patient Communications.** AI drafts SMS/portal messages. Human reviews and approves before sending.
 
### Safety Requirements
 
**Human-in-the-loop.** Human approval required for: patient communication, clinical workflow actions (closing an alert), escalations, clinical decisions.
 
**AI must never:** prescribe medication, make autonomous care decisions, send patient communications without approval, modify patient records without human review.
 
**Transparency.** AI outputs include: reasoning summary, source signals, confidence indicator.
 
```text
AI confidence: Medium
Signals used:
- Missing glucose reading
- Previous elevated reading
- Patient message
```
 
**Audit logging.** All AI activity generates events: `ai.summary.generated`, `ai.recommendation.generated`, `ai.response.drafted`, `ai.output.approved`, `ai.output.rejected`.
 
### Context Retrieval (RAG)
 
AI uses structured context from the Operational Data Graph (Section 3) plus curated documents (clinical protocols, communication guidelines, device troubleshooting, operational playbooks). Documents may be stored in Snowflake and/or indexed in a vector store (pgvector, Weaviate, or Pinecone).
 
Retrieval bundle:
 
```text
- last 5 alerts
- recent interactions
- open tasks
- relevant clinic protocol reference
```
 
### Learning from Outcomes
 
```text
AI recommendation → human action → outcome recorded
```
 
Over time, this supports reduced false positives and better triage suggestions.
 
### Architecture
 
```text
Operational Data Graph → Context retrieval → LLM API → AI assist service → Slack
```
 
The AI assist service is stateless: prompt construction, context retrieval, output formatting, audit logging. Easily replaceable.
 
### HIPAA Controls
 
Minimize PHI in prompts. Retrieve PHI on-demand from protected systems rather than embedding it in context. Encrypted transport, secure model endpoints, RBAC, audit logs. BAA coverage for LLM providers.
 
### Cost Management
 
- Cache summaries for identical/replayed contexts
- Use the smallest model that meets quality requirements
- Rate-limit per channel/clinic/alert type
- Prefer structured graph context over long raw text prompts
---
 
## 6. Implementation Blueprint
 
### Services
 
The full system:
 
```text
event-ingestion-service
event-backbone        (Redpanda)
event-store           (Postgres)
graph-projection
graph-api             (GraphQL / Hasura)
control-plane
slack-bot
ai-assist-service
warehouse-sync        (Snowflake + dbt)
```
 
The MVP requires five:
 
```text
event-ingestion-service
event-backbone
event-store
control-plane
slack-bot
```
 
### Technology Stack
 
```text
Language:       Python
API framework:  FastAPI
Messaging:      Redpanda (Kafka-compatible)
Database:       Postgres
Graph API:      GraphQL (Hasura or thin service)
AI provider:    OpenAI / Anthropic
Warehouse:      Snowflake
Transforms:     dbt
Interface:      Slack (Bolt framework)
```
 
### Repository Structure
 
```text
ocean/
  services/
    event-ingestion/
    event-store/
    graph-projection/
    control-plane/
    slack-bot/
  libs/
    ocean-events/   (shared event schemas + envelope)
  infra/
  docs/
```
 
### Event Ingestion Service
 
Converts external system activity into OCEAN events. Consumes webhooks, polls APIs when necessary, normalizes into canonical schema, publishes to backbone. This is the Phase 1 deliverable — universal event capture, no automation. Without this event layer, any downstream automation is guesswork.
 
Sources: Impilo (RPM signals), POCAR (alerts), ZCC (call events), Slack (care actions), Linear/GitHub (engineering), HubSpot (marketing), PAP/ExDash (customer success).
 
### Graph Projection Service
 
Listens to event streams, updates graph tables in Postgres, maintains entity relationships. `alert.created` → create Alert node; `task.created` → create Task node + Alert→Task edge; `call.completed` → create Interaction node + Task→Interaction edge.
 
### Control Plane Service
 
Evaluates rules, generates tasks, handles escalation logic, enforces operational policies.
 
v1: Python rule engine. Later: Temporal workflows (only if complexity demands it).
 
### Slack Bot
 
Slack Bolt framework (Python or Node.js). Posts alert notifications, captures task claims/completions, displays operational context, routes AI recommendations.
 
### AI Assist Service
 
Builds prompts, retrieves context from graph, calls LLM API, formats output for Slack, records audit events. Stateless; no persistent state beyond what the event store holds.
 
### Warehouse Sync
 
Events flow from backbone to Snowflake via export/ELT. dbt transforms for operational analytics, model training, alert optimization, reporting.
 
---
 
## 7. Production Operations
 
### Deployment
 
1. **Docker Compose** for dev environments and early integration testing.
2. **Single cluster** (Kubernetes, ECS, or similar) for staging + production.
3. Horizontal scale only after event schemas and runbooks stabilize.
### Environments
 
- **dev:** Local and sandbox integrations; synthetic/de-identified payloads.
- **staging:** Full integration tests against real connectors; production-like schemas.
- **prod:** Audited configs; strict access controls.
Any environment that touches PHI must have production-grade encryption, RBAC, and audit logging.
 
### CI/CD
 
1. Lint + unit tests
2. Event schema validation (breaking-change detection)
3. Database migration checks
4. Build/push container images
5. Deploy to staging
6. Integration tests (connectors + backbone + consumers)
7. Manual approval → deploy to prod
### Observability
 
Four questions the system must always answer: Are we ingesting events? Are consumers keeping up? Are tasks being created/claimed/completed? Are alerts being resolved or dismissed?
 
**Backbone health:** Consumer lag per topic/consumer group, publish rate (events/sec), error rate.
 
**Workflow health:** `alert.created` rate by type, `alert.dismissed` rate (false positives), task backlog by priority, mean time `alert.created` → `task.claimed` → `call.completed` → `alert.resolved`.
 
**AI health:** `ai.summary.generated` latency, approval/rejection rate, cost per triage.
 
Every workflow is traceable via `event_id`, `correlation_id`, and `source_system`. Tooling: Prometheus, Grafana, OpenTelemetry.
 
### Reliability Patterns
 
**Idempotency.** All consumers treat events as at-least-once. Use `event_id` as dedup key in Postgres; upserts and conflict handling.
 
**Retries + DLQ.** Exponential backoff for transient failures. Dead letter queue with full error context for poison messages.
 
**Schema versioning.** Version event schemas, enforce backward compatibility, treat schema changes like database migrations.
 
### Runbooks
 
**Connector down / event drop:** Check connector health endpoint + logs. Confirm upstream webhook/API auth. Replay missed window via polling backfill or source export.
 
**Consumer lag:** Identify slow consumer group and topic. Scale replicas or reduce per-event work. If necessary, temporarily disable non-critical consumers (e.g., AI assist) to protect core care workflows.
 
**Slack outage:** Continue recording events and generating tasks. Route fallback notifications (email/pager) for urgent alerts.
 
**ZCC outage:** Keep tasks open. Allow manual call workflow; record outcome events after the fact.
 
### Security
 
- No PHI in events (identifiers + metadata only)
- TLS everywhere; encryption at rest (Postgres, Redpanda, Snowflake)
- Least-privilege RBAC for data access, Slack bot actions, connector credentials
- Centralized secrets management (e.g., AWS Secrets Manager)
- Audit logs for event publication, Slack actions, AI outputs
- BAA coverage for third-party services that touch PHI
---
 
## Appendix — Key Integrations
 
### Impilo (RPM Device Platform)
 
Primary source of the Signal layer. Ingest: device shipment/activation, patient readings (`signal.received`), missing readings (`signal.missing`), anomalous readings (`signal.anomalous`).
 
### Zoom Contact Center (ZCC)
 
Call lifecycle events: `call.started`, `call.connected`, `call.completed`, `call.missed`. Attached to the patient interaction graph.
 
### Citrix / EHR
 
Care team accesses EHR via Citrix — human-operated systems. Actions there should generate events where possible (initially manual, automated later): `patient_medication_changed`, `visit_scheduled`, `note_added`.
 
### Departmental Systems
 
Linear/GitHub (engineering events), HubSpot/Customer.io (marketing events), POCAR (care alerts), PAP/ExDash (customer success events). Each integrates by emitting domain events through isolated connector services.