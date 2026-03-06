"""Pydantic models for Ocean operational entities.

These represent graph state — not events. They are used by graph projection
workers and the control plane to represent current entity state.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ocean_events.types import (
    AlertSeverity,
    AlertStatus,
    InteractionOutcome,
    ResolutionStatus,
    TaskPriority,
    TaskStatus,
)


class Patient(BaseModel):
    """Enrolled patient in the Ocean system. patient_id is an opaque hash — no PHI."""

    patient_id: str
    clinic_id: str
    enrollment_status: Literal["active", "inactive", "pending"]
    enrolled_at: datetime | None = None


class Clinic(BaseModel):
    """Care clinic with its timezone configuration."""

    clinic_id: str
    name: str
    timezone: str


class CareTeamMember(BaseModel):
    """Staff member on the care team with their Slack identity and role."""

    member_id: str
    slack_user_id: str
    role: Literal["nurse", "support", "analyst", "admin"]


class Signal(BaseModel):
    """Clinical signal reading from POCAR or another source."""

    signal_id: str
    patient_id: str  # opaque hash
    signal_type: str  # "glucose_reading" | "blood_pressure" | etc.
    value: float | None = None  # numeric value — not PHI under de-identification
    unit: str | None = None
    received_at: datetime
    anomalous: bool = False


class Alert(BaseModel):
    """Clinical alert generated from an anomalous signal."""

    alert_id: str
    patient_id: str  # opaque hash
    alert_type: str  # "glucose_missing" | "bp_anomalous" | etc.
    severity: AlertSeverity
    status: AlertStatus
    source_system: str
    created_at: datetime
    correlation_id: str


class Task(BaseModel):
    """Operational task assigned to a care team member."""

    task_id: str
    alert_id: str
    patient_id: str  # opaque hash
    task_type: str  # "call_patient" | "review_chart"
    priority: TaskPriority
    status: TaskStatus
    assigned_to: str | None = None
    created_at: datetime


class Interaction(BaseModel):
    """Patient interaction (call or message) linked to a task."""

    interaction_id: str
    task_id: str
    patient_id: str  # opaque hash
    interaction_type: Literal["call", "message"]
    outcome: InteractionOutcome
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Outcome(BaseModel):
    """Care outcome recorded after an interaction.

    notes field accepts clinical codes only — no free-text PHI.
    """

    outcome_id: str
    interaction_id: str
    patient_id: str  # opaque hash
    outcome_type: str
    resolution_status: ResolutionStatus
    notes: str | None = None
    recorded_at: datetime
