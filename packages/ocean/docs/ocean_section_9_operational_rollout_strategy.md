# 9. Operational Rollout Strategy

This section describes how Brook can deploy the OCEAN architecture across the company without disrupting day-to-day operations.

It assumes the architectural baseline in Section 0 and the AI safety/governance boundaries in Section 5, and focuses on adoption sequencing and operating model choices.

The rollout strategy assumes:

- ~170 employees
- ~35 care team members
- ~15 engineers
- ~5 engineers available to build internal platform capabilities
- Slack as the operational interface
- HIPAA / PHI constraints
- Human-in-the-loop AI policy
The goal is **incremental operational transformation**, not a large platform migration.

---

## Adoption Philosophy

OCEAN should not force teams to change their tools.

Departments retain their own optimized software stacks:

| Department | Systems |
|---|---|
| Care Team | POCAR, Zoom Contact Center |
| Customer Success | PAP, ExDash |
| Engineering | Slack, Linear, GitHub |
| Marketing | Slack, HubSpot, Customer.io |
| Data & Analytics | Snowflake, dbt |

Instead of replacing tools, OCEAN introduces a universal event layer connecting them.

```text
Department tools
      │
      ▼
OCEAN event backbone
      │
      ▼
Operational graph (Postgres) + analytics (Snowflake)
      │
      ▼
Slack operational interface
```

This keeps teams productive while enabling **cross-department coordination**.

---

## First Operational Pilot

The most strategic place to launch OCEAN is the **care alert → patient outreach loop**.

This is where the company currently experiences:

- the highest operational volume
- the highest false positive rate
- the highest patient impact
Current workflow:

```text
Patient signal
      ↓
Alert
      ↓
Care team review
      ↓
Patient phone call
      ↓
Outcome
```

OCEAN instruments this pipeline first.

Pilot scope:

- ingest alerts from POCAR
- send alerts/tasks to Slack
- capture care team decisions (Slack actions)
- capture Zoom Contact Center call outcomes
- store events in the operational event store (Postgres) and export to Snowflake
This pilot builds the **first operational learning loop**.

---

## Department Integration Strategy

After the pilot stabilizes, each department becomes a **node on the event backbone**.

### Care Team

Events (aligned to the canonical taxonomy in Section 1):

```text
signal.received / signal.missing
alert.created
alert.dismissed
task.created
task.claimed
call.started
call.connected
call.completed
```

Sources:

- POCAR
- Zoom Contact Center
---

### Engineering

Events (examples; organizations can add more over time):

```text
engineering.issue.created
engineering.issue.closed
pull_request.opened
pull_request.merged
incident.reported
```

Sources:

- Linear
- GitHub
These events allow correlation between:

- product releases
- operational incidents
- patient alerts
---

### Customer Success

Events:

```
customer.case.opened
customer.case.resolved
clinic.rule.changed
integration.issue.reported
```

Sources:

- PAP
- ExDash
---

### Marketing

Events:

```
campaign.launched
patient.message.sent
patient.message.clicked
patient.lifecycle.updated
```

Sources:

- HubSpot
- Customer.io
---

### Data & Analytics

Events:

```
model.updated
dashboard.viewed
dataset.published
data_quality_alert
```

Sources:

- Snowflake
- dbt
---

## Governance Model

A system like OCEAN requires **clear governance**.

Ownership should be distributed across three groups.

### Platform owner

Responsible for:

- event backbone
- operational graph
- system reliability
Suggested owner:

```
Data & Analytics + Platform Engineering
```

---

### Domain owners

Each department owns the events originating from their systems.

Example:

| Department | Event Ownership |
|---|---|
| Care Team | `signal.*`, `alert.*`, `task.*`, `call.*` |
| Engineering | `engineering.*`, `pull_request.*`, `incident.*` |
| Customer Success | `customer.case.*`, `clinic.rule.*`, `integration.*` |
| Marketing | `campaign.*`, `patient.message.*`, `patient.lifecycle.*` |

---

### AI governance

A cross-functional committee defines rules for AI use.

Responsibilities:

- PHI safety
- prompt policies
- auditability
- human-in-the-loop enforcement
No AI system should perform clinical actions autonomously.

---

## Measuring Success

Success metrics should focus on **operational improvement**.

Care operations:

- false positive alert rate
- mean time to patient outreach
- call completion rate
- patient engagement outcomes
Engineering:

- mean time to incident resolution
- production defect detection time
Customer success:

- integration issue resolution time
- clinic onboarding speed
Platform health:

- event processing latency
- event completeness rate
- AI recommendation acceptance rate
---

## Long-Term Evolution

Once the system matures, OCEAN becomes Brook's **operational nervous system**.

Capabilities will include:

Operational intelligence
- detecting systemic operational patterns
Predictive operations
- anticipating patient risk events
AI knowledge assistants
- surfacing institutional knowledge instantly
Cross-department orchestration
- connecting engineering, care, and support workflows
At that point the architecture stops being an internal tool and becomes **Brook's operational OS**.

---

## One Strategic Insight

Most companies treat operations as **fragmented systems and manual workflows**.

But modern digital health companies require **continuous operational intelligence**.

Brook's real internal product becomes:

```
A continuously learning operational system
```

Where every signal, alert, task, interaction, and outcome contributes to a growing operational knowledge graph.

This system:

- improves care delivery
- improves engineering response
- improves patient engagement
- improves institutional memory
The OCEAN architecture transforms Brook from a **collection of tools** into a **learning operational organism**.
