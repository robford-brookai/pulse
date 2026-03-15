"""Event and entity type aliases for Ocean events."""
from __future__ import annotations

from typing import Literal

SourceSystem = Literal[
    "pocar", "zcc", "ocean", "linear", "github", "hubspot", "impilo",
    "control-plane", "agent-worker", "call-simulator", "sim-driver",
]

EntityType = Literal[
    "patient", "alert", "task", "interaction", "outcome", "signal", "ticket",
    "fulfillment", "return", "device_association",
]

AlertSeverity = Literal["critical", "high", "medium", "low"]

AlertStatus = Literal["open", "claimed", "resolved", "dismissed"]

TaskPriority = Literal["critical", "high", "medium", "low"]

TicketCategory = Literal["device_issue", "patient_activation", "clinical_support", "engineering_it"]

TicketStatus = Literal["open", "in_progress", "waiting", "resolved"]

TicketPriority = Literal["critical", "high", "medium", "low"]

WaitingReason = Literal["external_block", "timed_pause", "patient_response"]

CATEGORY_PREFIXES: dict[str, str] = {
    "device_issue": "DEV",
    "patient_activation": "ACT",
    "clinical_support": "CLN",
    "engineering_it": "ENG",
}

TaskStatus = Literal["open", "claimed", "completed", "canceled"]

InteractionOutcome = Literal["completed", "missed", "pending"]

ResolutionStatus = Literal["resolved", "escalated", "pending"]

# Composite alias for event type strings — dot-namespaced, past-tense
EventType = Literal[
    "signal.received",
    "signal.missing",
    "signal.anomalous",
    "alert.created",
    "alert.triaged",
    "alert.escalated",
    "alert.resolved",
    "alert.dismissed",
    "task.created",
    "task.assigned",
    "task.claimed",
    "task.completed",
    "task.canceled",
    "call.started",
    "call.connected",
    "call.completed",
    "call.missed",
    "outcome.recorded",
    "ai.summary.generated",
    "ai.response.drafted",
    "ai.output.approved",
    "ai.recommendation.generated",
    "ai.output.rejected",
    "ticket.created",
    "ticket.updated",
    "ticket.resolved",
    "fulfillment.updated",
    "return.updated",
    "device.associated",
    "device.disassociated",
    "scenario.started",
    "scenario.completed",
]
