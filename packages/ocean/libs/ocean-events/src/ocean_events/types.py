"""Event and entity type aliases for Ocean events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceSystem = Literal[
    "pocar",
    "zcc",
    "ocean",
    "linear",
    "github",
    "hubspot",
    "impilo",
    "control-plane",
    "agent-worker",
    "call-simulator",
    "sim-driver",
    "mongodb-connector",
]

EntityType = Literal[
    "patient",
    "alert",
    "task",
    "interaction",
    "outcome",
    "signal",
    "ticket",
    "fulfillment",
    "return",
    "device_association",
    "pull_request",
    "commit",
    "contact",
    "patient_feature",
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

ResolutionType = Literal["resolved", "false_positive", "completed", "missed"]


@dataclass(frozen=True)
class OutcomeRecorded:
    """Normalized outcome event payload for the ocean.outcomes stream."""

    entity_type: str  # "task" | "ticket" | "alert" | "call"
    entity_id: str
    resolution_type: str  # "resolved" | "false_positive" | "completed" | "missed"
    resolved_by: str
    correlation_id: str


# Composite alias for event type strings — dot-namespaced, past-tense
EventType = Literal[
    "signal.received",
    "signal.missing",
    "signal.anomalous",
    "alert.created",
    "alert.triaged",
    "alert.escalated",
    "alert.resolved",
    "alert.snoozed",
    "alert.unsnoozed",
    "alert.dismissed",
    "task.created",
    "task.assigned",
    "task.claimed",
    "task.completed",
    "task.canceled",
    "task.escalated",
    "ticket.escalated",
    "call.started",
    "call.connected",
    "call.completed",
    "call.missed",
    "outcome.recorded",
    "ai.summary.generated",
    "ai.response.drafted",
    "ai.output.approved",
    "ai.output.confirmed",
    "ai.output.overridden",
    "ai.recommendation.generated",
    "ai.output.rejected",
    "connector.heartbeat",
    "ticket.created",
    "ticket.updated",
    "ticket.resolved",
    "fulfillment.updated",
    "return.updated",
    "device.associated",
    "device.disassociated",
    "scenario.started",
    "scenario.completed",
    "pr.opened",
    "pr.merged",
    "pr.closed",
    "commit.pushed",
    "contact.created",
    "contact.updated",
    "contact.deleted",
    "patient.feature.changed",
]
