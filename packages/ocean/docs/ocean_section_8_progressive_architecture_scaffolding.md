# 8. Progressive Architecture Scaffolding
 
This section describes how the OCEAN architecture should be built progressively, enabling rapid internal feedback and minimizing risk.
 
The goal is not to launch a full platform immediately, but to scaffold capabilities step-by-step so the organization learns while building.
 
This section assumes the architectural baseline from Section 0 and the canonical event taxonomy/envelope from Section 1, and focuses on implementation sequencing.
 
Key constraints at Brook:
 
- ~170 employees
- ~5 engineers available for platform work
- Slack is the operational interface for the company
- Care team operations produce the highest event volume
- HIPAA / PHI compliance required
- AI must remain **human-in-the-loop**
The scaffolding strategy therefore prioritizes:
 
1. **Slack-first workflows**
2. **Event capture before automation**
3. **Visibility before orchestration**
4. **Assistive AI before autonomous AI**
---
 
## Guiding Principles
 
The architecture rollout should follow five principles.
 
### 1) Instrument first
 
Before building automation, the company must **observe its operational system**.
 
This means capturing events from:
 
- Slack
- Care alerts
- Engineering tickets
- Marketing workflows
- Patient contact outcomes
Without this event layer, automation becomes guesswork.
 
---
 
### 2) Slack as the operational surface
 
Slack already functions as the **company's control plane**.
 
Therefore the architecture should:
 
- Post alerts
- collect human decisions
- trigger workflows
- present AI assistance
directly in Slack.
 
Slack becomes the human interface to the operational graph.
 
---
 
### 3) Event-driven design
 
Every meaningful operational action becomes an **event**.
 
Examples (aligned to the canonical taxonomy from Section 1):
 
```text
signal.received
signal.missing
alert.created
alert.dismissed
task.created
task.claimed
call.completed
patient.consent_recorded
```
 
These events feed the **operational data graph**.
 
---
 
### 4) Human-in-the-loop AI
 
AI is allowed to:
 
- summarize
- recommend
- draft responses
- prioritize work
AI is **not allowed to autonomously execute clinical workflows**.
 
All clinical actions require human confirmation.
 
---
 
### 5) Replaceability of tools
 
Departments can choose their own tools.
 
But every tool must connect through:
 
```text
OCEAN event backbone
```
 
This keeps the company flexible if tools change.
 
---
 
## Phase 1 — Event capture layer
 
The first capability to implement is **universal event capture**.
 
No automation yet.
 
Just instrumentation.
 
### Goal
 
Create a central event stream representing company operations.
 
### Minimal architecture
 
```text
Slack
Care Systems (POCAR)
Customer Success (PAP / ExDash)
Engineering (Linear / GitHub)
Marketing (HubSpot)
 
        │
        ▼
 
 Event collector service
        │
        ▼
  Event backbone (Redpanda)
 
        │
        ▼
 
 Event store + exports
   - Postgres (operational event store)
   - Snowflake (analytics)
```
 
### Implementation tasks
 
Engineers build lightweight connectors that capture:
 
| Source | Events |
|---|---|
| Slack | message, reaction, thread activity |
| Linear | issue created, updated |
| GitHub | PR opened, merged |
| POCAR | `signal.*`, `alert.created`, `alert.resolved`, `alert.dismissed` |
| PAP / ExDash | customer case events |
| HubSpot | contact lifecycle events |
 
Each event gets a standardized envelope (see Section 1).
 
Example:
 
```json
{
  "event_type": "alert.created",
  "timestamp": "...",
  "source_system": "pocar",
  "patient_id": "...",
  "alert_type": "...",
  "metadata": {...}
}
```
 
Operationally, events are written to the Postgres event store and projected into the operational graph; they can also be exported to Snowflake for analytics.
 
### Outcome (visibility)
 
The company gains **full visibility into operational activity**.
 
---
 
## Phase 2 — Operational data graph
 
Once events are captured, the next step is constructing an **operational graph model**.
 
The graph represents relationships between:
 
- patients
- care alerts
- employees
- tickets
- engineering changes
- clinical workflows
### Graph Example
 
```
Patient
  │
  ├─ generates → Care Alert
  │
  ├─ assigned to → Care Team Member
  │
  └─ associated with → Clinic
 
Care Alert
  │
  ├─ triggers → Slack Discussion
  │
  ├─ triggers → Patient Call
  │
  └─ creates → Engineering Issue
```
 
### Storage
 
Prefer a direct operational projection into Postgres (graph tables) from the event backbone (see Section 3). Snowflake remains the analytics system.
 
### Outcome (graph context)
 
The company can answer questions like:
 
- Which alerts generate engineering work?
- Which clinics generate the most false positives?
- Which alert types cause patient outreach?
---
 
## Phase 3 — Slack operational bots
 
Next, introduce **Slack bots that use the operational graph**.
 
Bots assist humans with context and triage.
 
Examples:
 
### Care Alert Bot
 
Posts alerts to Slack channel:
 
```text
#care-alerts
```
 
Example message:
 
```text
New Alert: Blood Pressure Spike
 
Patient: 47291
Clinic: Evergreen Health
 
Historical alerts: 4
Previous outreach: Yes
 
AI Summary:
Likely medication non-adherence.
```
 
Human choices:
 
```text
[Call Patient]
[Dismiss Alert]
[Escalate to Clinic]
```
 
Each click generates an event.
 
---
 
### Engineering insight bot
 
Posts correlations like:
 
```text
Alert Type: Missing Glucose Data
 
Spike detected after last mobile app release.
 
Related PR:
github.com/.../pull/491
```
 
This surfaces **systemic issues faster**.
 
---
 
## Phase 4 — AI knowledge layer
 
Once events and graph exist, the next layer is **knowledge accumulation**.
 
Operational knowledge includes:
 
- Slack conversations
- resolved alerts
- engineering fixes
- patient outreach outcomes
- clinic rule adjustments
All these artifacts should be stored in Snowflake (analytics) and/or a protected document store, then indexed into:
 
```text
Vector Knowledge Store
```
 
Example pipeline:
 
```text
Snowflake
   │
   ▼
Knowledge Extractor
   │
   ▼
Embedding Generator
   │
   ▼
Vector Store
```
 
Possible technologies:
 
- pgvector
- Weaviate
- Pinecone
---
 
## Phase 5 — AI operational assistants
 
Now AI can assist operational workflows.
 
### Care Assistant
 
AI summarizes alerts:
 
```text
Alert: Irregular Heart Rate
 
Summary:
Similar alerts occurred twice last month and resolved
after medication adjustment.
 
Suggested Action:
Call patient and confirm medication adherence.
```
 
Human confirms before action.
 
---
 
### Patient communication assistant
 
AI drafts messages:
 
```text
Hello [Patient Name],
 
Our care team noticed a recent blood pressure reading
outside your usual range. We'd like to check in.
 
Would you be available for a quick call today?
```
 
Human approves before sending.
 
---
 
### Internal operations assistant
 
AI answers questions like:
 
```text
Which alert types generate the most false positives?
```
 
or
 
```
Which clinics generate alerts requiring engineering fixes?
```
 
---
 
## Phase 6 — Workflow orchestration
 
Only after the previous layers are stable should the system begin **automating workflows**.
 
Example:
 
```text
alert.created
        │
        ▼
AI Summarizes Alert
        │
        ▼
Slack Notification
        │
        ▼
Human Decision
        │
   ┌────┴─────┐
   ▼          ▼
Call Patient  Dismiss
   │
   ▼
Zoom Contact Center Call
   │
   ▼
Call Outcome Event
```
 
The system orchestrates **but does not decide**.
 
---
 
## Phase 7 — Intelligent operations
 
Eventually the operational graph enables deeper insights.
 
Examples:
 
### Predictive Alert Filtering
 
AI learns which alerts are false positives.
 
Alert triage improves.
 
---
 
### Clinic Quality Analytics
 
Identify clinics with problematic rules.
 
---
 
### Engineering Impact Analysis
 
Detect when product changes affect patient monitoring.
 
---
 
## Final architecture vision
 
After full rollout the architecture looks like this:
 
```text
Operational Tools
Slack
POCAR
PAP / ExDash
HubSpot
Linear
GitHub
 
        │
        ▼
 
Event backbone
(Redpanda)
 
        │
        ▼
 
Postgres operational store + exports
 
        │
        ▼
 
Operational Data Graph
(projected from events)
 
        │
        ▼
 
AI Knowledge Layer
(Vector Store)
 
        │
        ▼
 
Slack Operational Bots
+ AI Assistants
```
 
Slack remains the **human control interface**.
 
Snowflake remains the analytics warehouse.
 
The event backbone remains the integration backbone.
 
---
 
## Why this approach works
 
This progressive scaffolding:
 
- avoids large platform rewrites
- provides value immediately
- builds institutional knowledge
- keeps engineering scope manageable
Most importantly:
 
The organization **learns about its own operations while building the system that runs them**.
 
This is the central philosophy of the **OCEAN architecture**.