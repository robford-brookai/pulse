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
    Ticket,
)
from ocean_events.types import (
    CATEGORY_PREFIXES,
    AlertSeverity,
    AlertStatus,
    EntityType,
    EventType,
    InteractionOutcome,
    ResolutionStatus,
    SourceSystem,
    TaskPriority,
    TaskStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    WaitingReason,
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
    "Ticket",
    # Types
    "AlertSeverity",
    "AlertStatus",
    "CATEGORY_PREFIXES",
    "EntityType",
    "EventType",
    "InteractionOutcome",
    "ResolutionStatus",
    "SourceSystem",
    "TaskPriority",
    "TaskStatus",
    "TicketCategory",
    "TicketPriority",
    "TicketStatus",
    "WaitingReason",
]
