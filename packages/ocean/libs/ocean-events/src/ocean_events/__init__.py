"""Ocean Events — canonical event schema and entity models."""
from ocean_events.base import _PHI_FIELD_NAMES, BaseEvent
from ocean_events.entities import (
    Alert,
    CareTeamMember,
    Clinic,
    Interaction,
    Outcome,
    Patient,
    Signal,
    Task,
)
from ocean_events.types import (
    AlertSeverity,
    AlertStatus,
    EntityType,
    EventType,
    InteractionOutcome,
    ResolutionStatus,
    SourceSystem,
    TaskPriority,
    TaskStatus,
)

__all__ = [
    "BaseEvent",
    "_PHI_FIELD_NAMES",
    # Entities
    "Alert",
    "CareTeamMember",
    "Clinic",
    "Interaction",
    "Outcome",
    "Patient",
    "Signal",
    "Task",
    # Types
    "AlertSeverity",
    "AlertStatus",
    "EntityType",
    "EventType",
    "InteractionOutcome",
    "ResolutionStatus",
    "SourceSystem",
    "TaskPriority",
    "TaskStatus",
]
