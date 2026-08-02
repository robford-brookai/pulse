"""Integration: out-of-order call outcome delivery converges (DNA-738).

The audit's worst case: `call.completed` and `call.missed` for the same
engagement, delivered in either order. Before the sequence guard the last
message to *arrive* won, so a completed call could be silently rewritten to
missed. After the guard the event with the later *envelope timestamp* wins,
whichever order the two arrive in.

Run: `python -m pytest tests/integration/test_outcome_ordering.py -m integration`
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import sqlalchemy as sa

pytestmark = pytest.mark.integration

_STARTED_AT = "2026-03-05T10:00:00Z"
_MISSED_AT = "2026-03-05T10:01:00Z"
_COMPLETED_AT = "2026-03-05T10:05:00Z"


def _event(event_type: str, engagement_id: str, event_id: str, timestamp: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "schema_version": "1.0.0",
        "source_system": "zcc",
        "entity_type": "interaction",
        "entity_id": engagement_id,
        "correlation_id": "corr-ordering",
        "actor_id": "agent-1",
        "timestamp": timestamp,
        "payload": {
            "patient_id": "pt-ordering-001",
            "task_id": "task-ordering-001",
            "disposition": "resolved",
        },
    }


_SEED_STATEMENTS = [
    "INSERT INTO patients (patient_id, clinic_id, enrollment_status, updated_at) "
    "VALUES ('pt-ordering-001', 'clinic-1', 'active', NOW()) "
    "ON CONFLICT (patient_id) DO NOTHING",
    "INSERT INTO alerts (alert_id, patient_id, alert_type, severity, status, "
    "source_system, created_at, updated_at, correlation_id) "
    "VALUES ('alert-ordering-001', 'pt-ordering-001', 'glucose_high', 'URGENT', 'open', "
    "'pocar', NOW(), NOW(), 'corr-ordering') "
    "ON CONFLICT (alert_id) DO NOTHING",
    "INSERT INTO tasks (task_id, alert_id, patient_id, task_type, priority, status, "
    "created_at, updated_at) "
    "VALUES ('task-ordering-001', 'alert-ordering-001', 'pt-ordering-001', 'outreach', "
    "'high', 'open', NOW(), NOW()) "
    "ON CONFLICT (task_id) DO NOTHING",
]


@pytest_asyncio.fixture(scope="module")
async def seed_graph(session_factory):
    """Prerequisite patient/alert/task rows for the interactions FK constraints."""
    async with session_factory() as session, session.begin():
        for statement in _SEED_STATEMENTS:
            await session.execute(sa.text(statement))


async def _deliver(session_factory, engagement_id: str, order: list[tuple[str, str, str]]) -> dict:
    """Project a sequence of events, then return the resulting interactions row."""
    from src.handlers.interactions import handle_call_started
    from src.handlers.outcomes import handle_call_completed, handle_call_missed

    handlers = {
        "call.started": handle_call_started,
        "call.completed": handle_call_completed,
        "call.missed": handle_call_missed,
    }
    for event_type, event_id, timestamp in order:
        async with session_factory() as session, session.begin():
            await handlers[event_type](_event(event_type, engagement_id, event_id, timestamp), session)

    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    sa.text("SELECT outcome, last_event_id, last_event_at FROM interactions WHERE interaction_id = :i"),
                    {"i": engagement_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


@pytest.mark.asyncio
async def test_reverse_delivery_reaches_the_same_state(session_factory, seed_graph):
    """completed(10:05) then missed(10:01), and the reverse, converge on 'completed'."""
    in_order = await _deliver(
        session_factory,
        "eng-order-fwd",
        [("call.missed", "evt-missed-1", _MISSED_AT), ("call.completed", "evt-completed-1", _COMPLETED_AT)],
    )
    reversed_order = await _deliver(
        session_factory,
        "eng-order-rev",
        [("call.completed", "evt-completed-2", _COMPLETED_AT), ("call.missed", "evt-missed-2", _MISSED_AT)],
    )

    assert in_order["outcome"] == "completed"
    assert reversed_order["outcome"] == "completed", "a stale call.missed rewrote a completed call"
    assert in_order["last_event_at"] == reversed_order["last_event_at"]


@pytest.mark.asyncio
async def test_stale_missed_does_not_clear_the_completed_event_pointer(session_factory, seed_graph):
    """The rejected event must not leave its own event_id behind as `last_event_id`."""
    row = await _deliver(
        session_factory,
        "eng-order-pointer",
        [("call.completed", "evt-completed-3", _COMPLETED_AT), ("call.missed", "evt-missed-3", _MISSED_AT)],
    )

    assert row["last_event_id"] == "evt-completed-3"


@pytest.mark.asyncio
async def test_later_missed_still_wins(session_factory, seed_graph):
    """The guard drops stale writes, not all writes — a genuinely later event applies."""
    row = await _deliver(
        session_factory,
        "eng-order-later-missed",
        [
            ("call.completed", "evt-completed-4", _MISSED_AT),
            ("call.missed", "evt-missed-4", _COMPLETED_AT),
        ],
    )

    assert row["outcome"] == "missed"


@pytest.mark.asyncio
async def test_guard_applies_over_a_row_with_no_event_time(session_factory, seed_graph):
    """call.started (task 3.2, still unguarded) leaves last_event_at NULL.

    A NULL-unsafe guard would silently drop the outcome write onto that row.
    """
    row = await _deliver(
        session_factory,
        "eng-order-null",
        [
            ("call.started", "evt-started-5", _STARTED_AT),
            ("call.completed", "evt-completed-5", _COMPLETED_AT),
        ],
    )

    assert row["outcome"] == "completed"
    assert row["last_event_id"] == "evt-completed-5"


@pytest.mark.asyncio
async def test_redelivery_of_the_same_event_is_idempotent(session_factory, seed_graph):
    """At-least-once delivery: the same event twice leaves the same row."""
    first = await _deliver(
        session_factory,
        "eng-order-dupe",
        [("call.completed", "evt-completed-6", _COMPLETED_AT)],
    )
    second = await _deliver(
        session_factory,
        "eng-order-dupe",
        [("call.completed", "evt-completed-6", _COMPLETED_AT)],
    )

    assert first == second
