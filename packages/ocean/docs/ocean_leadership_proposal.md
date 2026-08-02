# OCEAN: An Operational Platform for Brook
 
## What This Document Is
 
This is the leadership case for OCEAN — Brook's event-driven operational platform. It describes the problem, the architectural direction, the pilot plan, the phased roadmap, and how we'll measure success.
 
A separate [Technical Reference](./ocean_technical_reference.md) covers event schemas, object models, query patterns, deployment, and implementation details.
 
---
 
## The Problem
 
Brook's care operations run on strong, specialized tools. POCAR handles alerts. Impilo delivers device data. ZCC handles calls. Slack handles coordination. Snowflake handles analytics. Each tool is good at its job.
 
The problem is between the tools.
 
<!-- REPLACE THIS BLOCK with sourced data before publishing. See the Evidence Brief for sourcing instructions. -->
 
**Operational volume (source: POCAR + Snowflake):**
 
- ~200 care alerts/day, of which approximately 70% are false positives
- ~30 support tickets/day
- ~15 engineering issues/day
**What we cannot currently measure:**
 
- How long it takes from alert to patient contact
- Which alerts lead to calls, and which calls resolve alerts
- Which alert types produce the most false positives, by clinic
- Whether a product release caused a spike in care alerts
These aren't dashboard gaps. They're operational blind spots. We generate ~200 alerts/day and have no structured way to track whether any of them resulted in patient contact, let alone whether that contact resolved the underlying issue.
 
<!-- END EVIDENCE BLOCK -->
 
The pattern is consistent across departments:
 
- **Care → Engineering:** A nurse notices a pattern in alerts that suggests a software bug. The path to engineering is a Slack message, a manually created Linear ticket, and hope that someone connects the dots.
- **Engineering → Care:** A product release changes alert behavior. No one correlates the release with the alert spike until a nurse mentions it days later in Slack.
- **Care → Outcome:** A nurse calls a patient. The outcome is recorded nowhere that the system can learn from — the next nurse who sees the same alert type starts from scratch.
This is not a tools problem. It is a coordination problem. The operational data exists, but it is trapped inside systems that don't talk to each other.
 
The goal is to move from:
 
> alerts → operational chaos
 
to:
 
> signals → tasks → actions → outcomes → learning
 
---
 
## The Architectural Insight
 
The instinct is to build a unified ticketing system — one schema for all work across departments. This fails for three predictable reasons:
 
1. **Semantic drift.** Support tickets, care alerts, and engineering issues are not the same thing. Forcing them into one abstraction creates ambiguity that teams route around.
2. **Integration fragility.** A central bus with adapters for every system becomes brittle. When one adapter breaks, the bus becomes unreliable.
3. **Ownership conflict.** No department wants to own a shared ticketing system. It becomes a shadow system.
OCEAN takes a different approach: **events, not tickets.**
 
Every meaningful operational action — an alert firing, a task being claimed, a call completing, an outcome being recorded — becomes an immutable event on a shared backbone. Departments keep their own tools. OCEAN connects them by making their activity observable and queryable.
 
The acronym:
 
- **O**perational Control Plane — routing, rules, human approvals
- **C**ontrol Plane → Slack — the operational interface
- **E**vent Backbone — durable event transport
- **A**nalytics Graph — the operational data model + relationships
- **N**exus for AI — summaries, recommendations, institutional memory
This is not a novel architectural category. Stripe, Airbnb, Uber, and Amazon each built internal event-driven operational platforms when they reached a stage where the coordination cost between teams exceeded the capacity of ad hoc workflows. Brook is at that stage now — but in a clinical context where the coordination failures affect patient care.
 
---
 
## What OCEAN Looks Like
 
```text
Department tools (POCAR, Impilo, ZCC, Linear, GitHub, HubSpot, Slack)
        │
        ▼
Event backbone (captures what happened)
        │
        ▼
Operational graph (connects signals, alerts, tasks, calls, outcomes)
        │
        ├──► Analytics (Snowflake + dbt)
        │
        ▼
Slack control plane (surfaces decisions, captures human actions)
        │
        ▼
AI assist (summaries + recommendations, human-approved)
        │
        ▼
Outcome events (learning loop)
```
 
Five principles govern the architecture:
 
1. **Do not replace existing systems.** Wrap them with events.
2. **Slack is the operational UI.** Teams already live there.
3. **Events are facts; tasks are derived.** The control plane turns facts into work.
4. **AI assists but humans act.** No autonomous clinical decisions.
5. **Build visibility before automation.** Observe the system before optimizing it.
---
 
## The Pilot: Care Alert Loop
 
The care alert → patient outreach loop is where OCEAN pays for itself first.
 
It has the highest operational volume (~200 alerts/day), the highest noise (~70% false positives), and the most direct patient impact. It is also the loop where the gap between "alert fired" and "outcome recorded" is currently invisible.
 
Current workflow:
 
```text
Patient signal (Impilo) → Alert (POCAR) → Nurse review (Slack/manual) → Call (ZCC) → Outcome (untracked)
```
 
OCEAN instruments this pipeline end to end:
 
```text
signal.received → alert.created → task.created → task.claimed → call.completed → alert.resolved
```
 
Every step becomes an event. For the first time, we can measure the full loop — and start learning from it.
 
Pilot scope:
 
- Ingest device signals from Impilo
- Ingest alerts from POCAR
- Route alerts/tasks to Slack
- Capture care team decisions (Slack button clicks → events)
- Capture ZCC call outcomes
- Store all events in Postgres; export to Snowflake
This produces Brook's first operational learning loop. Every subsequent phase builds on the data it generates.
 
---
 
## Phased Roadmap
 
Each phase ships a deployable increment. Phases are ordered by dependency, not calendar.
 
### Phase 1 — Event Capture
 
Make operations observable. No automation yet. Build lightweight connectors for the pilot systems (Impilo, POCAR, Slack, ZCC). Every operational action becomes a recorded event.
 
**Outcome:** The company can see its operational activity for the first time.
 
### Phase 2 — Operational Data Graph
 
Project events into a queryable graph (Postgres). Answer questions we currently cannot: Which alert types produce the most false positives? Which alerts led to calls? Which clinics generate the most engineering work?
 
**Outcome:** Operational questions that required hours of investigation become instant queries.
 
### Phase 3 — Slack Control Plane
 
Surface alerts and tasks directly in Slack. Care team members claim and complete work in place. Button clicks generate events.
 
The system also surfaces cross-domain correlations that are currently invisible. Example Slack message in an engineering channel:
 
```text
Alert Type: Missing Glucose Data
 
Spike detected after last mobile app release.
 
Related PR:
github.com/.../pull/491
```
 
This kind of correlation — a product release caused a care alert spike — currently takes days of manual investigation if it's discovered at all.
 
**Outcome:** Slack becomes the operations console, not just a communication tool.
 
### Phase 4 — AI Assist
 
Add alert summarization, triage recommendations, and draft patient messages. All outputs require human approval. AI is grounded in the operational graph, not arbitrary text.
 
**Outcome:** Faster triage, better documentation, reduced cognitive load — with clinical authority preserved.
 
### Phase 5 — Workflow Orchestration
 
Connect the control plane rules, Slack interface, ZCC integration, and AI assist into end-to-end orchestrated workflows. The system orchestrates but does not decide.
 
**Outcome:** Alert-to-outcome workflows are coordinated rather than manual.
 
### Phase 6 — Learning Loop
 
Use outcome data to improve alert thresholds, AI recommendations, and clinic workflow rules. This is how the false positive rate decreases over time.
 
<!-- EVIDENCE NEEDED: Set a measurable target before Phase 6 ships. E.g., "Reduce false positive alert rate from ~70% to ≤40% within 6 months of Phase 6 launch." -->
 
**Outcome:** The system gets smarter with use.
 
The phased approach is not just risk management. Each phase generates the data and organizational understanding that makes the next phase possible. The organization learns about its own operations while building the system that runs them.
 
---
 
## Technology and Team
 
OCEAN can be delivered as ~6–9 services by a five-engineer team. The MVP (Phase 1–3) requires only five services.
 
Technology: Python/FastAPI, Redpanda (Kafka-compatible), Postgres, GraphQL, Slack Bolt, Snowflake + dbt. AI via OpenAI/Anthropic with BAA coverage.
 
No exotic infrastructure. No custom orchestration frameworks. Existing, well-understood tools composed into an event-driven system.
 
---
 
## HIPAA and Safety
 
Events carry identifiers and metadata only — **no PHI in the event stream**. Protected systems (POCAR, EHR) retrieve patient data on demand using reference IDs.
 
AI never executes clinical actions autonomously. All patient communications, alert closures, and escalations require human approval. All AI outputs are auditable via events (`ai.summary.generated`, `ai.output.approved`, `ai.output.rejected`).
 
Full audit trail: every event records actor, timestamp, source system, and correlation ID. End-to-end traceability from signal to outcome.
 
---
 
## Governance
 
Ownership is distributed across three groups:
 
**Platform owner** (Data & Analytics + Platform Engineering): event backbone, operational graph, system reliability.
 
**Domain owners** — each department owns events from their systems:
 
| Department | Owns |
|---|---|
| Care Team | Signals, alerts, tasks, calls |
| Engineering | Issues, PRs, incidents |
| Customer Success | Cases, clinic rules, integration issues |
| Marketing | Campaigns, patient messaging, lifecycle |
 
**AI governance** (cross-functional committee): PHI safety, prompt policies, auditability, human-in-the-loop enforcement.
 
---
 
## How We Measure Success
 
<!-- EVIDENCE NEEDED: Establish current baselines for every metric below before Phase 1 ships. Without baselines, improvement is unmeasurable. -->
 
**Care operations:**
- False positive alert rate (baseline: ~70%)
- Mean time from alert to patient contact (baseline: currently unmeasured)
- Call completion rate
- Patient engagement outcomes
**Engineering:**
- Mean time to incident resolution
- Time to detect production defects affecting care operations
**Platform health:**
- Event processing latency
- Event completeness rate
- AI recommendation acceptance rate
---
 
## What Can Go Wrong
 
Seven failure modes, in order of likelihood:
 
1. **No organizational adoption.** Engineers build the system; operations ignores it. *Mitigation:* Start with one painful loop (care alerts) and solve it completely. If that workflow becomes dramatically easier, adoption spreads.
2. **Event taxonomy chaos.** Teams emit inconsistent events. *Mitigation:* Central event schema registry with versioning. Domain owners propose; platform owner approves.
3. **Slack notification overload.** Every event becomes a notification; staff ignores the system. *Mitigation:* Slack surfaces decisions, not raw events. Priority filtering, digest summaries, channel routing.
4. **AI hallucinating clinical advice.** *Mitigation:* AI is restricted to summarization, recommendation, and drafting. No autonomous clinical action. Human approval required for all outputs.
5. **Over-engineering the platform.** *Mitigation:* Use Postgres, Redpanda, Snowflake, Slack. Only introduce complexity when proven necessary.
6. **Tool integration fragility.** Third-party APIs break. *Mitigation:* Every integration is an isolated connector service. Individual failures don't collapse the system.
7. **PHI data leakage.** *Mitigation:* No PHI in events. Strict data classification. Access policies in Snowflake. Audit logging for AI queries.
---
 
## Bottom Line
 
OCEAN is not a speculative platform bet. It is a practical operating model upgrade: connect existing tools through a shared event layer, make operational activity visible and queryable, and build a learning loop from signals to outcomes.
 
It can be delivered incrementally by a small team, measured in operational KPIs, and scaled as Brook grows.
 
The hardest part is not the technology. It is defining the event schema, designing the task model, and encoding workflow rules. Those are organizational decisions — and making them explicitly is itself a valuable outcome.
 
The architecture succeeds when the company experiences a specific shift: operational questions that once required hours of investigation become answerable instantly. At that point the system stops being infrastructure and becomes organizational intelligence.
 
---
 
*Technical Reference: [ocean_technical_reference.md](./ocean_technical_reference.md)*
*Evidence Brief: [ocean_evidence_brief.md](./ocean_evidence_brief.md)*