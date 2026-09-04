# 2. Operational Object Model

## Purpose

The Operational Object Model defines the small set of canonical entities OCEAN uses to represent operational state and work at Brook.

- The **event taxonomy** (Section 1) describes *what happened*.
- The **object model** defines *what exists* (and what the Operational Data Graph can connect).
Design goals:

- support the care loop (signals → alerts → tasks → interactions → outcomes)
- integrate multiple systems without becoming vendor-specific
- remain small enough for a ~5‑engineer team to maintain
Core philosophy: **few entities, many events**.

> Note on HIPAA/PHI: events should contain identifiers + metadata only. The object model may include PHI-bearing attributes, but in practice OCEAN should store the minimum operational state needed and retrieve PHI from protected systems on demand, with strict RBAC and audit logging.

## Core Objects

| Object | What it represents |
|---|---|
| Patient | The central subject of care operations (identified by `patient_id`). |
| Clinic | The partner organization and its policies/protocols. |
| CareTeamMember | A staff member who performs operational work. |
| Signal | Raw incoming patient telemetry (device readings, missing readings, surveys, messages). |
| Alert | A triaged signal requiring review and potential action. |
| Task | A human work item created by the control plane. |
| Interaction | Communication with the patient (call, SMS, portal message, scheduling). |
| Outcome | The result of an interaction, used for learning and policy improvement. |

## Object Categories (Layers)

The model is organized into four layers:

1. Identity layer
2. Signal layer
3. Work layer
4. Interaction layer
## Identity Layer

### Patient

Represents an enrolled individual receiving care services.

Common attributes:

- `patient_id`
- `clinic_id`
- `program_enrollment`
- `consent_status`
- `risk_profile`
- `external_references` (IDs in source systems)
Relationships:

```text
Patient
  ├─ Signals
  ├─ Alerts
  ├─ Tasks
  └─ Interactions
```

### Clinic

Represents a partner healthcare organization.

Common attributes:

- `clinic_id`
- `ehr_system`
- `rpm_programs`
- `clinical_rules_ref` (pointers to protocols/policies)
### CareTeamMember

Represents internal clinical or operational staff.

Common attributes:

- `staff_id`
- `role` (nurse, support, physician, analyst)
- `team`
- `availability`
- `permissions`
## Signal Layer

### Signal

Signals represent incoming patient data *before* triage.

Sources include RPM devices, surveys, messages, and missing readings.

Common attributes:

- `signal_id`
- `patient_id`
- `signal_type`
- `value` (when present)
- `timestamp`
- `source_system`
Relationship:

```text
Signal → may_trigger → Alert
```

## Work Layer

### Alert

Alerts are triaged signals requiring review.

Common attributes:

- `alert_id`
- `patient_id`
- `signal_id` (optional)
- `alert_type`
- `severity`
- `status` (open, escalated, resolved, dismissed)
Relationship:

```text
Alert → generates → Task
```

### Task

Tasks represent human work items (e.g., call patient, review alert, escalate).

Common attributes:

- `task_id`
- `patient_id`
- `alert_id` (optional)
- `task_type`
- `priority`
- `status`
- `assigned_staff_id` (optional)
Relationship:

```text
Task → resolved_by → Interaction
```

## Interaction Layer

### Interaction

Interactions represent patient communication.

Types include phone calls, SMS messages, chat, and appointment scheduling.

Common attributes:

- `interaction_id`
- `patient_id`
- `interaction_type`
- `start_time`
- `end_time`
- `status`
## Outcome

Outcome captures the result of an interaction.

Examples:

- patient educated
- medication clarified
- device malfunction identified
- escalation required
Common attributes:

- `outcome_id`
- `interaction_id`
- `outcome_type`
- `resolution_status`
- `notes_ref` (pointer to protected notes if needed)
## Object Relationships (Operational Lifecycle)

The operational lifecycle typically looks like this:

```text
Patient
  └─ Signal
      └─ Alert
          └─ Task
              └─ Interaction
                  └─ Outcome
```

## Example Operational Flow

Example scenario: patient misses a glucose reading.

```text
Signal (missing_reading)
→ Alert (glucose_missing)
→ Task (call_patient)
→ Interaction (phone_call)
→ Outcome (patient_educated)
```

## Design Principles

### Small Core Model

The operational model intentionally contains fewer than ~10 primary objects to prevent schema explosion and brittle integrations.

### Event-Sourced State

Objects are materialized views of events.

Example:

```text
Task.status is derived from:
  task.created
  task.assigned
  task.completed
```

### System-Agnostic Design

Objects must not be tied to specific vendor tools.

For example, an `Interaction` represents calls regardless of whether they originate from Zoom Contact Center, Twilio, or an EHR call log.

## Why This Model Works

The object model matches Brook’s operational reality:

- alerts trigger work
- work results in patient interactions
- interactions produce outcomes that drive learning
By structuring the system around these objects, OCEAN becomes a coordination layer rather than another application silo.
