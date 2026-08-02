"""Tests for ticket-related types, entity, and priority unification."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Literal type members
# ---------------------------------------------------------------------------


class TestTicketCategory:
    def test_members(self):
        from ocean_events.types import TicketCategory

        expected = {"device_issue", "patient_activation", "clinical_support", "engineering_it"}
        assert set(get_args(TicketCategory)) == expected


class TestTicketStatus:
    def test_members(self):
        from ocean_events.types import TicketStatus

        expected = {"open", "in_progress", "waiting", "resolved"}
        assert set(get_args(TicketStatus)) == expected


class TestTicketPriority:
    def test_members(self):
        from ocean_events.types import TicketPriority

        expected = {"critical", "high", "medium", "low"}
        assert set(get_args(TicketPriority)) == expected


class TestWaitingReason:
    def test_members(self):
        from ocean_events.types import WaitingReason

        expected = {"external_block", "timed_pause", "patient_response"}
        assert set(get_args(WaitingReason)) == expected


class TestCategoryPrefixes:
    def test_maps_all_categories(self):
        from ocean_events.types import CATEGORY_PREFIXES, TicketCategory

        categories = set(get_args(TicketCategory))
        assert set(CATEGORY_PREFIXES.keys()) == categories

    def test_prefix_values(self):
        from ocean_events.types import CATEGORY_PREFIXES

        assert CATEGORY_PREFIXES["device_issue"] == "DEV"
        assert CATEGORY_PREFIXES["patient_activation"] == "ACT"
        assert CATEGORY_PREFIXES["clinical_support"] == "CLN"
        assert CATEGORY_PREFIXES["engineering_it"] == "ENG"


# ---------------------------------------------------------------------------
# Unified priority scale (AlertSeverity + TaskPriority)
# ---------------------------------------------------------------------------


class TestUnifiedPriority:
    def test_alert_severity_unified(self):
        from ocean_events.types import AlertSeverity

        expected = {"critical", "high", "medium", "low"}
        assert set(get_args(AlertSeverity)) == expected

    def test_task_priority_unified(self):
        from ocean_events.types import TaskPriority

        expected = {"critical", "high", "medium", "low"}
        assert set(get_args(TaskPriority)) == expected


# ---------------------------------------------------------------------------
# EventType and EntityType extensions
# ---------------------------------------------------------------------------


class TestEventTypeExtensions:
    def test_ticket_events_in_event_type(self):
        from ocean_events.types import EventType

        members = set(get_args(EventType))
        assert "ticket.created" in members
        assert "ticket.updated" in members
        assert "ticket.resolved" in members


class TestEntityTypeExtension:
    def test_ticket_in_entity_type(self):
        from ocean_events.types import EntityType

        assert "ticket" in get_args(EntityType)


# ---------------------------------------------------------------------------
# Ticket entity
# ---------------------------------------------------------------------------


class TestTicketEntity:
    def test_construction_all_fields(self):
        from ocean_events.entities import Ticket

        t = Ticket(
            ticket_id="tkt-001",
            human_id="DEV-00001",
            category="device_issue",
            priority="high",
            status="open",
            patient_id="pt-001",
            description="Device not transmitting",
            waiting_reason=None,
            created_at=_now(),
            correlation_id="corr-001",
        )
        assert t.ticket_id == "tkt-001"
        assert t.human_id == "DEV-00001"
        assert t.category == "device_issue"
        assert t.priority == "high"
        assert t.status == "open"
        assert t.patient_id == "pt-001"

    def test_engineering_ticket_no_patient(self):
        from ocean_events.entities import Ticket

        t = Ticket(
            ticket_id="tkt-002",
            human_id="ENG-00001",
            category="engineering_it",
            priority="medium",
            status="open",
            patient_id=None,
            description="CI pipeline broken",
            created_at=_now(),
            correlation_id="corr-002",
        )
        assert t.patient_id is None

    def test_waiting_reason(self):
        from ocean_events.entities import Ticket

        t = Ticket(
            ticket_id="tkt-003",
            human_id="CLN-00001",
            category="clinical_support",
            priority="critical",
            status="waiting",
            description="Awaiting patient callback",
            waiting_reason="patient_response",
            created_at=_now(),
            correlation_id="corr-003",
        )
        assert t.waiting_reason == "patient_response"

    def test_invalid_category_rejected(self):
        from ocean_events.entities import Ticket

        with pytest.raises(ValidationError):
            Ticket(
                ticket_id="tkt-bad",
                human_id="BAD-00001",
                category="invalid_category",
                priority="low",
                status="open",
                description="test",
                created_at=_now(),
                correlation_id="corr-bad",
            )

    def test_invalid_priority_rejected(self):
        from ocean_events.entities import Ticket

        with pytest.raises(ValidationError):
            Ticket(
                ticket_id="tkt-bad",
                human_id="BAD-00001",
                category="device_issue",
                priority="urgent",  # old value, no longer valid
                status="open",
                description="test",
                created_at=_now(),
                correlation_id="corr-bad",
            )


# ---------------------------------------------------------------------------
# Task.alert_id now optional
# ---------------------------------------------------------------------------


class TestTaskAlertIdOptional:
    def test_task_without_alert_id(self):
        from ocean_events.entities import Task

        t = Task(
            task_id="tk-001",
            alert_id=None,
            patient_id="pt-001",
            task_type="call_patient",
            priority="medium",
            status="open",
            created_at=_now(),
        )
        assert t.alert_id is None

    def test_task_with_alert_id(self):
        from ocean_events.entities import Task

        t = Task(
            task_id="tk-002",
            alert_id="al-001",
            patient_id="pt-001",
            task_type="call_patient",
            priority="high",
            status="open",
            created_at=_now(),
        )
        assert t.alert_id == "al-001"


# ---------------------------------------------------------------------------
# Exports from __init__.py
# ---------------------------------------------------------------------------


class TestExports:
    def test_ticket_exported(self):
        from ocean_events import Ticket

        assert Ticket is not None

    def test_ticket_types_exported(self):
        from ocean_events import (
            CATEGORY_PREFIXES,
            TicketCategory,
            TicketPriority,
            TicketStatus,
            WaitingReason,
        )

        all_types = [
            TicketCategory,
            TicketStatus,
            TicketPriority,
            WaitingReason,
            CATEGORY_PREFIXES,
        ]
        assert all(t is not None for t in all_types)
