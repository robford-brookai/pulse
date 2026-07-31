
# 7. Deployment & Operations
 
## Purpose
 
This section describes how to deploy and operate OCEAN in production at Brook’s scale:
 
- ~170 employees
- a small platform team (≈5 engineers)
- **Slack-first operations**
- HIPAA/PHI constraints
The goal is operational reliability and auditability without building a heavyweight platform.
 
## Runtime Architecture (Operational Services)
 
OCEAN is a small set of long-running services connected by an event backbone.
 
```text
External Systems
  (POCAR, ZCC, Slack, Linear/GitHub, HubSpot, etc.)
        │
        ▼
Connectors / Ingestion
  (webhooks + polling + normalization)
        │
        ▼
Event Backbone (Redpanda)
        │
        ├──► Event Store (Postgres)
        ├──► Graph Projection (consumers → Postgres)
        ├──► Control Plane (rules/routing → publishes events)
        ├──► Slack Bot (threads + actions → publishes events)
        ├──► AI Assist (RAG + summaries → publishes events)
        └──► Warehouse Export (Snowflake + dbt)
```
 
Operationally, the most important property is **at-least-once event delivery + idempotent consumers**.
 
## Deployment Model (Simple First)
 
Start with a deployment model a small team can own:
 
- containerized services
- managed Postgres
- a small Redpanda cluster (or managed Kafka)
Suggested progression:
 
1. **Docker Compose** for developer environments and early integration testing.
2. **Single cluster deployment** (Kubernetes, ECS, or similar) for staging + production.
3. Add horizontal scale only after you have stable event schemas and runbooks.
## Environments
 
Maintain three environments:
 
- **dev:** local and sandbox integrations; synthetic/de-identified payloads when possible.
- **staging:** full integration tests against real connectors; production-like schemas.
- **prod:** audited configs only; strict access controls.
Key rule: if PHI is ever accessed by a service, ensure the environment has the same controls (encryption, RBAC, audit logging) you would expect in production.
 
## CI/CD
 
CI/CD should be schema-first and safety-first.
 
Minimum pipeline:
 
1. Lint + unit tests
2. Event schema validation (breaking-change detection)
3. Database migration checks
4. Build/push container images
5. Deploy to staging
6. Integration tests (connectors + backbone + consumers)
7. Manual approval → deploy to prod
## Observability
 
OCEAN is only operable if you can answer:
 
- Are we ingesting events?
- Are consumers keeping up?
- Are tasks being created/claimed/completed?
- Are alerts being resolved (or dismissed as false positives)?
### Core Metrics
 
#### Backbone / stream health
 
- consumer lag per topic/consumer group
- publish rate (events/sec)
- error rate (publish failures, auth failures)
#### Operational workflow health
 
- `alert.created` rate by alert type
- `alert.dismissed` rate (false positives)
- task backlog by type / priority
- mean time: `alert.created` → `task.claimed` → `call.completed` → `alert.resolved`
#### AI health (if enabled)
 
- `ai.summary.generated` latency
- approval/rejection rate (`ai.output.approved` / `ai.output.rejected`)
- cost per alert triage
### Logs and Traces
 
Every workflow should be traceable end-to-end using:
 
- `event_id`
- `correlation_id` (one per workflow chain)
- `source_system`
## Reliability Patterns
 
### Idempotency
 
All consumers should treat events as at-least-once:
 
- use `event_id` as a dedup key in Postgres
- make writes idempotent (upserts, conflict handling)
### Retries + Dead Letter Queue (DLQ)
 
- retry transient failures with exponential backoff
- send poison messages to a DLQ topic/table with full error context
### Schema Versioning
 
- version event schemas
- enforce backward compatibility
- treat schema changes like database migrations
## Security & HIPAA Controls
 
OCEAN must assume HIPAA-level safeguards:
 
- **No PHI in events** (identifiers + metadata only)
- TLS everywhere; encryption at rest (Postgres, Redpanda/Kafka, Snowflake)
- least-privilege RBAC for:
  - data access (warehouse + operational DB)
  - Slack bot actions
  - connector credentials
- centralized secrets management (e.g., AWS Secrets Manager)
- audit logs for:
  - event publication
  - Slack actions that create/complete tasks
  - AI outputs and approvals
If a third-party service touches PHI (including an LLM provider), ensure the appropriate contractual posture (e.g., BAA) and technical controls.
 
## Data Retention, Backups, and Replay
 
OCEAN relies on replayability:
 
- retain backbone topics long enough to replay (hours → days depending on needs)
- keep the Postgres event store as the durable, queryable audit trail
- run automated backups for Postgres and regularly test restores
## Runbooks (Common Incidents)
 
### Connector Down / Event Drop
 
1. Check connector health endpoint + logs.
2. Confirm upstream webhook/API auth.
3. Replay missed time window (polling backfill or source export).
### Consumer Lag / Backlog
 
1. Identify the slow consumer group and topic.
2. Scale consumer replicas or reduce per-event work.
3. If necessary: temporarily disable non-critical consumers (e.g., AI assist) to protect core care workflows.
### Slack or ZCC Outage
 
Slack outage:
 
- continue recording events and generating tasks
- route fallback notifications (email/pager) for urgent alerts
ZCC outage:
 
- keep tasks open
- allow manual call workflow with outcome events recorded after the fact
## Cost Management (AI)
 
If AI assist is enabled:
 
- cache summaries for identical/replayed contexts
- use the smallest model that meets quality requirements
- rate-limit per channel/clinic/alert type
- prefer structured context (graph) over long raw text prompts
## Scaling Path
 
Only after the taxonomy + workflows stabilize:
 
- add more connectors (Linear/GitHub, HubSpot, PAP/ex-dash)
- add multi-region redundancy if needed
- tighten SLOs around the care loop (`alert.created` → `call.completed`)
The core operational scaling strategy remains the same:
 
> stable schemas + replayable events + idempotent consumers + strong observability