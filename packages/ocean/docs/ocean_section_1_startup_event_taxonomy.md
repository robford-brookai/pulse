1. Startup Event Taxonomy
Purpose

The Startup Event Taxonomy defines the canonical operational events that describe what happens across Brook.

Instead of systems communicating through tightly coupled integrations, every meaningful change in the operational system is represented as an event.

Events become the shared language of operations, enabling:

loose coupling between systems
real-time operational awareness
workflow automation and analytics
AI-assisted workflows (human-in-the-loop)
auditability (especially important in HIPAA environments)
Event Design Principles
1) Events represent facts

Events describe something that already happened. They are not commands.

Examples:

alert.created
task.assigned
call.completed

Not:

create_alert
assign_task

Commands trigger actions. Events record outcomes.

2) Events are immutable (append-only)

Events should not be edited in place.

Instead of:

alert.updated

Prefer:

alert.status_changed
3) Events are contextual

Every event should include, at minimum:

entity_id
timestamp
actor
source_system

Example payload:

json
{
  "event_type": "alert.created",
  "timestamp": "2026-03-05T18:20:00Z",
  "source_system": "rpm-platform",
  "patient_id": "pt_283847",
  "alert_type": "glucose_missing",
  "severity": "routine"
}
Event Categories

The taxonomy is organized into six operational domains:

Patient lifecycle
Clinical signals
Alerts
Tasks
Interactions
AI operations
1) Patient Lifecycle Events

These events describe changes to patient records or program enrollment.

Event	Description
patient.created	Patient record created
patient.updated	Patient demographic or metadata updated
patient.enrolled	Patient enrolled in program
patient.unenrolled	Patient removed from program
patient.consent_recorded	Consent captured
patient.consent_revoked	Consent withdrawn
2) Clinical Signal Events

Signals represent raw incoming patient data (not yet alerts).

Examples include RPM device readings, symptom reports, and missing measurements.

Event	Description
signal.received	Incoming clinical measurement
signal.missing	Expected signal not received
signal.anomalous	Signal outside expected range

Example payload:

json
{
  "event_type": "signal.received",
  "patient_id": "pt_84723",
  "signal_type": "glucose_reading",
  "value": 195,
  "unit": "mg/dL"
}
3) Alert Events

Alerts represent triaged clinical signals requiring review (by a nurse and/or AI).

Event	Description
alert.created	Alert generated
alert.triaged	Nurse or AI triaged alert
alert.escalated	Alert escalated
alert.resolved	Alert resolved
alert.dismissed	False positive

Given Brook’s environment where ~70% of alerts are false positives, capturing alert.dismissed is essential for learning.

4) Task Events

Tasks represent human work assignments.

Event	Description
task.created	Work item generated
task.assigned	Task assigned to staff
task.claimed	Worker claimed task
task.started	Work began
task.completed	Task finished
task.canceled	Task no longer required

Example chain:

text
alert.created
→ task.created
→ task.claimed
→ task.completed
5) Interaction Events

Interactions capture communication with patients.

Event	Description
call.started	Phone call initiated
call.connected	Call answered
call.completed	Call finished
call.missed	Patient did not answer
message.sent	Message sent to patient
message.received	Message received from patient

For Brook this integrates directly with Zoom Contact Center.

6) AI Operation Events

AI activity must also be recorded to support safety and auditability.

Event	Description
ai.summary.generated	Alert summary created
ai.recommendation.generated	Suggested action generated
ai.response.drafted	Patient message drafted
ai.feedback.recorded	Human accepted/rejected output
Example End-to-End Event Flow

Example workflow: patient misses a glucose reading.

text
signal.missing
→ alert.created
→ ai.summary.generated
→ ai.recommendation.generated
→ task.created
→ task.claimed
→ call.started
→ call.completed
→ alert.resolved

Every operational action becomes observable and analyzable.

Event Envelope Standard

All events should share a common envelope.

json
{
  "event_id": "evt_123",
  "event_type": "alert.created",
  "timestamp": "ISO8601",
  "source_system": "rpm",
  "entity_id": "alert_456",
  "entity_type": "alert",
  "payload": {}
}
Why This Matters

The taxonomy is the foundation of OCEAN.

Without a stable event language:

integrations become brittle
analytics becomes fragmented
AI cannot learn from outcomes

With a stable taxonomy, departmental tools become loosely coupled nodes on an operational nervous system.
