"""Tests for Ocean entity models and type literals."""
from __future__ import annotations

from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# All entities importable
# ---------------------------------------------------------------------------


def test_all_entities_importable():
    """All eight entity models are importable from ocean_events.entities."""
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

    assert all(
        cls is not None
        for cls in [Alert, CareTeamMember, Clinic, Interaction, Outcome, Patient, Signal, Task]
    )


def test_event_type_literals_importable():
    """EventType, EntityType and other type aliases are importable from ocean_events.types."""
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

    assert all(
        t is not None
        for t in [
            AlertSeverity,
            AlertStatus,
            EntityType,
            EventType,
            InteractionOutcome,
            ResolutionStatus,
            SourceSystem,
            TaskPriority,
            TaskStatus,
        ]
    )


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------


def test_patient_model_validates():
    """Patient with valid fields constructs correctly."""
    from ocean_events.entities import Patient

    p = Patient(
        patient_id="pt-001",
        clinic_id="clinic-001",
        enrollment_status="active",
        enrolled_at=_now(),
    )
    assert p.patient_id == "pt-001"
    assert p.enrollment_status == "active"


def test_patient_invalid_status():
    """Patient with invalid enrollment_status raises ValidationError."""
    import pytest
    from pydantic import ValidationError

    from ocean_events.entities import Patient

    with pytest.raises(ValidationError):
        Patient(patient_id="pt-001", clinic_id="clinic-001", enrollment_status="unknown")


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------


def test_alert_severity_literal():
    """Alert with invalid severity raises ValidationError."""
    import pytest
    from pydantic import ValidationError

    from ocean_events.entities import Alert

    with pytest.raises(ValidationError):
        Alert(
            alert_id="al-001",
            patient_id="pt-001",
            alert_type="glucose_missing",
            severity="invalid",  # not in Literal
            status="open",
            source_system="pocar",
            created_at=_now(),
            correlation_id="corr-001",
        )


def test_alert_valid():
    """Alert with valid fields constructs correctly."""
    from ocean_events.entities import Alert

    a = Alert(
        alert_id="al-001",
        patient_id="pt-001",
        alert_type="glucose_missing",
        severity="urgent",
        status="open",
        source_system="pocar",
        created_at=_now(),
        correlation_id="corr-001",
    )
    assert a.severity == "urgent"
    assert a.status == "open"


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


def test_task_status_literal():
    """Task with invalid status raises ValidationError."""
    import pytest
    from pydantic import ValidationError

    from ocean_events.entities import Task

    with pytest.raises(ValidationError):
        Task(
            task_id="tk-001",
            alert_id="al-001",
            patient_id="pt-001",
            task_type="call_patient",
            priority="routine",
            status="bogus",  # not in Literal
            created_at=_now(),
        )


def test_task_valid():
    """Task with valid fields constructs correctly."""
    from ocean_events.entities import Task

    t = Task(
        task_id="tk-001",
        alert_id="al-001",
        patient_id="pt-001",
        task_type="call_patient",
        priority="routine",
        status="open",
        assigned_to=None,
        created_at=_now(),
    )
    assert t.priority == "routine"
    assert t.assigned_to is None


# ---------------------------------------------------------------------------
# Other entity smoke tests
# ---------------------------------------------------------------------------


def test_clinic_valid():
    """Clinic with valid fields constructs correctly."""
    from ocean_events.entities import Clinic

    c = Clinic(clinic_id="cl-001", name="Brook Health", timezone="America/New_York")
    assert c.timezone == "America/New_York"


def test_care_team_member_valid():
    """CareTeamMember with valid role constructs correctly."""
    from ocean_events.entities import CareTeamMember

    m = CareTeamMember(member_id="m-001", slack_user_id="U12345", role="nurse")
    assert m.role == "nurse"


def test_signal_valid():
    """Signal with valid fields constructs correctly."""
    from ocean_events.entities import Signal

    s = Signal(
        signal_id="sig-001",
        patient_id="pt-001",
        signal_type="glucose_reading",
        value=120.5,
        unit="mg/dL",
        received_at=_now(),
        anomalous=True,
    )
    assert s.anomalous is True
    assert s.value == 120.5


def test_interaction_valid():
    """Interaction with valid fields constructs correctly."""
    from ocean_events.entities import Interaction

    i = Interaction(
        interaction_id="int-001",
        task_id="tk-001",
        patient_id="pt-001",
        interaction_type="call",
        outcome="pending",
    )
    assert i.interaction_type == "call"
    assert i.outcome == "pending"


def test_outcome_valid():
    """Outcome with valid fields constructs correctly."""
    from ocean_events.entities import Outcome

    o = Outcome(
        outcome_id="out-001",
        interaction_id="int-001",
        patient_id="pt-001",
        outcome_type="resolved",
        resolution_status="resolved",
        recorded_at=_now(),
    )
    assert o.resolution_status == "resolved"
