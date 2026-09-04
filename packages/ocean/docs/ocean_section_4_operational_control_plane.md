
# 4. Operational Control Plane

## Purpose

The **Operational Control Plane** coordinates how work flows through Brook.

- The **Event Backbone** records what happened.
- The **Operational Data Graph** provides contextual state.
- The **Control Plane** determines what should happen next.
It is the layer that:

- triages signals and alerts
- generates and routes tasks
- enforces operational policies (SLA/escalation/coverage)
- coordinates human-in-the-loop AI assistance
In OCEAN, the control plane is the operational “brain”: it turns facts (events) into work (tasks) while preserving human authority.

## Responsibilities

The control plane typically implements five functions:

1. Signal triage
2. Task generation
3. Task routing
4. Human workflow coordination
5. Operational policy enforcement
## Inputs and Outputs

### Inputs

The control plane consumes events from the backbone, for example:

```text
signal.received
signal.missing
alert.created
alert.escalated
task.completed
call.completed
message.received
ai.recommendation.generated
```

### Outputs

The control plane publishes new operational events (and may trigger external side effects via connectors), for example:

```text
task.created
task.assigned
task.escalated
alert.resolved
alert.dismissed
```

## Core Workflow (Care Loop)

```text
Signal
  ↓
Alert
  ↓
AI Assist (summary/recommendation)
  ↓
Task Creation
  ↓
Task Routing
  ↓
Human Action
  ↓
Interaction Outcome
  ↓
Alert Resolution (or dismissal)
```

Every step produces observable events.

## Rule Engine

At the core of the control plane is a rule engine.

Rules evaluate incoming events and create tasks/workflows.

Example rule:

```text
IF signal.missing
AND signal.type = glucose_reading
AND patient.enrolled_in = diabetes_program

THEN create alert
THEN create task(call_patient)
```

Rules encode clinic policies and care protocols into operational logic.

## Task Generation

Tasks are the primary unit of operational work.

Typical task types:

- `call_patient`
- `review_alert`
- `verify_device_usage`
- `escalate_to_physician`
- `send_patient_message`
Minimum task fields (conceptually):

- `task_id`
- `patient_id`
- `alert_id` (optional)
- `task_type`
- `priority`
- `status`
- `assigned_staff_id` (optional)
## Task Routing

Task routing decides who should do the work.

Routing logic commonly considers:

- care team role
- clinic assignment
- nurse availability
- alert severity
- workload balancing
Example routing rule:

```text
IF task.type = call_patient
AND alert.severity = urgent

ROUTE TO on_call_nurse
```

## Slack as the Operational Interface

Slack is the human control surface: the control plane uses Slack to present decisions and capture human actions.

Example Slack alert:

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

Slack actions generate events:

```text
task.claimed
task.completed
task.reassigned
```

## Zoom Contact Center (ZCC) Integration

When a call task is executed, the workflow integrates with ZCC.

Example call lifecycle:

```text
task.claimed
→ call.started
→ call.connected
→ call.completed
```

These events are written back into the Operational Data Graph.

## Escalation Logic

Escalation prevents alerts from falling through operational gaps.

Examples:

```text
IF alert.severity = urgent
AND task.not_completed_after = 30 minutes

THEN escalate_to_physician
```

```text
IF patient_unreachable
THEN create follow_up_task
```

## Human-in-the-Loop Governance

Even when AI is used, the control plane ensures:

- humans approve actions
- clinical workflows remain supervised
- patient communications are reviewed
AI may suggest actions like `call_patient`, `send_followup_message`, or `schedule_visit`, but execution requires human confirmation.

## Observability and Failure Isolation

Because workflows generate events, the control plane enables full operational observability (response times, volumes, backlog, false positive rate).

It must also tolerate external outages:

- Slack unavailable: tasks still created; route urgent alerts via fallback notification.
- ZCC unavailable: keep tasks open; allow manual call workflows and record outcomes afterward.
## Why the Control Plane Matters

Without a control plane:

```text
alerts → dashboards → manual decisions → inconsistent outcomes
```

With a control plane:

```text
signals → alerts → tasks → actions → outcomes → learning
```

The control plane transforms scattered tools into coordinated, auditable care workflows.
