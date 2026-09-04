# Appendix A — OCEAN Architecture in One Page

The OCEAN architecture can be summarized as a single conceptual pipeline.

```text
Department Systems
────────────────────────────────────────

Care systems: POCAR
Customer Success: PAP / ExDash
Engineering: Linear + GitHub
Marketing: HubSpot + Customer.io
Communication: Slack
Patient contact: Zoom Contact Center
```

↓

```text
Event Integration Layer
────────────────────────────────────────

Connectors (webhooks + polling)
Normalization
Unified event envelope
```

↓

```text
OCEAN Event Backbone
────────────────────────────────────────

Redpanda (Kafka-compatible)
Event streams (topics)
```

↓

```text
Operational Data Layer
────────────────────────────────────────

Postgres event store
Operational data graph (projected from events)
Graph API (GraphQL)
```

↓

```text
Analytics + Knowledge Layer
────────────────────────────────────────

Snowflake + dbt (analytics)
Vector knowledge store (optional)
RAG retrieval
```

↓

```text
Operational Interface
────────────────────────────────────────

Slack bots
Human-in-the-loop workflows
AI assistants (summaries + recommendations)
```

↓

```text
Outcomes
────────────────────────────────────────

Care team actions
Engineering fixes
Patient outreach
Clinic improvements
```

This pipeline converts operational activity into **operational intelligence**.

---

## Appendix B — OCEAN Pre-Mortem: Probable Failure Modes

Before implementing OCEAN it is critical to understand how systems like this **fail in practice**.

---

## Failure Mode 1 — Event Taxonomy Chaos

Different teams emit inconsistent events.

Example:

```
alert_created
care_alert
patient_alert
bp_alert
```

Result:

Operational data becomes impossible to reason about.

Mitigation:

Create a **central event schema registry** with versioning.

---

## Failure Mode 2 — Slack Notification Overload

If every event becomes a Slack notification, employees will ignore the system.

Mitigation:

Implement:

- priority filtering
- digest summaries
- channel routing rules
Slack should surface **decisions**, not raw events.

---

## Failure Mode 3 — AI Hallucinating Clinical Advice

LLMs may generate unsafe recommendations.

Mitigation:

AI outputs must be restricted to:

- summarization
- drafting
- recommendation
Never direct clinical action.

All clinical decisions require human confirmation.

---

## Failure Mode 4 — Over-Engineering the Platform

Small engineering teams often try to build:

- full workflow engines
- custom orchestration frameworks
- complex graph infrastructure
Too early.

Mitigation:

Use existing infrastructure:

- Redpanda/Kafka
- Postgres
- Snowflake + dbt
- Slack
Only introduce complexity when proven necessary.

---

## Failure Mode 5 — Tool Integration Fragility

Third-party APIs break frequently.

Mitigation:

Every integration must be isolated via:

```
Connector Services
```

This allows individual integrations to fail without collapsing the event system.

---

## Failure Mode 6 — PHI Data Leakage

Operational data pipelines may accidentally expose patient information.

Mitigation:

Implement:

- strict data classification
- PHI tagging
- access policies in Snowflake
- audit logging for AI queries
---

## Failure Mode 7 — No Organizational Adoption

The most common failure.

Engineers build the system, but operations ignore it.

Mitigation:

Start with **one painful operational loop** and solve it completely.

At Brook, that loop is:

```text
alert → task → outreach → outcome
```

If that workflow becomes dramatically easier, adoption will spread organically.

---

## Final Observation

The OCEAN architecture succeeds when the company begins to experience a subtle shift:

Operational questions that once required hours of investigation become answerable instantly.

At that moment the system stops being infrastructure and becomes **organizational intelligence**.
