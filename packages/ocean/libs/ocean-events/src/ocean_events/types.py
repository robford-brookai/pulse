"""Event and entity type aliases for Ocean events."""
from __future__ import annotations

from typing import Literal

SourceSystem = Literal[
    "pocar", "zcc", "ocean", "linear", "github", "hubspot",
    "control-plane", "agent-worker", "call-simulator", "sim-driver",
]

EntityType = Literal["patient", "alert", "task", "interaction", "outcome", "signal"]

AlertSeverity = Literal["urgent", "routine", "low"]

AlertStatus = Literal["open", "claimed", "resolved", "dismissed"]

TaskPriority = Literal["urgent", "routine", "low"]

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
]
