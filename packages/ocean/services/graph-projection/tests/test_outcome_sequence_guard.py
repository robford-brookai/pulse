"""Sequence-guard unit tests for the call outcome projections (DNA-738).

The `interactions.outcome` upserts in `handlers/outcomes.py` were unguarded: a
`call.missed` delivered after a `call.completed` silently rewrote a completed
call to missed. Delivery is unordered, so the guard must compare *event* time —
`completed_at` is written with `datetime.now()` and is therefore disqualified
(see the `event-delivery` spec, "Sequence guards compare event time, never
processing time").

These tests assert the shape of the emitted SQL and the parameters bound to it.
The behavioural proof — reverse delivery reaching the same stored state — lives
in `tests/integration/test_outcome_ordering.py` against real Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    return session


def _make_call_event(event_type: str, timestamp: str = "2026-03-05T10:00:00Z", **payload_overrides) -> dict:
    payload = {"patient_id": "pt-001", "task_id": "", "disposition": "resolved"}
    payload.update(payload_overrides)
    return {
        "event_id": "evt-001",
        "event_type": event_type,
        "source_system": "zcc",
        "entity_id": "eng-1",
        "entity_type": "interaction",
        "actor_id": "agent-1",
        "timestamp": timestamp,
        "payload": payload,
    }


def _interaction_upsert(mock_session) -> tuple[str, dict]:
    """Return (sql, params) for the interactions upsert — always the first execute."""
    args, _ = mock_session.execute.call_args_list[0]
    return args[0].text, args[1]


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


# ---------------------------------------------------------------------------
# event_time helper
# ---------------------------------------------------------------------------


def test_event_time_parses_zulu_envelope_timestamp():
    from src.handlers.sequence import event_time

    assert event_time({"timestamp": "2026-03-05T10:00:00Z"}) == datetime(2026, 3, 5, 10, 0, tzinfo=UTC)


def test_event_time_passes_through_datetime():
    from src.handlers.sequence import event_time

    moment = datetime(2026, 3, 5, 10, 0, tzinfo=UTC)
    assert event_time({"timestamp": moment}) == moment


def test_event_time_assumes_utc_for_naive_timestamp():
    from src.handlers.sequence import event_time

    assert event_time({"timestamp": "2026-03-05T10:00:00"}) == datetime(2026, 3, 5, 10, 0, tzinfo=UTC)


def test_event_time_rejects_missing_timestamp():
    """No event time means no ordering. Raise rather than silently fall back to now()."""
    from src.handlers.sequence import event_time

    with pytest.raises(ValueError, match="no timestamp"):
        event_time({"event_id": "evt-001"})


def test_event_time_rejects_unparseable_timestamp():
    from src.handlers.sequence import event_time

    with pytest.raises(ValueError, match="unparseable"):
        event_time({"timestamp": "last tuesday"})


def test_sequence_guard_is_null_safe():
    """A row written before the guard column existed has NULL last_event_at.

    A bare `EXCLUDED.last_event_at > interactions.last_event_at` evaluates to
    NULL there and silently drops every update — the obvious fix that is wrong.
    """
    from src.handlers.sequence import sequence_guard

    guard = _normalize(sequence_guard("interactions"))
    assert "interactions.last_event_at IS NULL" in guard
    assert (
        "(EXCLUDED.last_event_at, EXCLUDED.last_event_id) > (interactions.last_event_at, interactions.last_event_id)"
        in guard
    )


# ---------------------------------------------------------------------------
# handler SQL shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "handler_name,event_type", [("handle_call_completed", "call.completed"), ("handle_call_missed", "call.missed")]
)
@pytest.mark.asyncio
async def test_outcome_upsert_carries_event_time_guard(mock_session, handler_name, event_type):
    import src.handlers.outcomes as outcomes

    await getattr(outcomes, handler_name)(_make_call_event(event_type), mock_session)
    sql, params = _interaction_upsert(mock_session)
    sql = _normalize(sql)

    assert "ON CONFLICT (interaction_id) DO UPDATE SET" in sql
    assert "last_event_at = EXCLUDED.last_event_at" in sql
    assert "interactions.last_event_at IS NULL" in sql
    assert (
        "(EXCLUDED.last_event_at, EXCLUDED.last_event_id) > (interactions.last_event_at, interactions.last_event_id)"
        in sql
    )
    assert params["event_at"] == datetime(2026, 3, 5, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "handler_name,event_type", [("handle_call_completed", "call.completed"), ("handle_call_missed", "call.missed")]
)
@pytest.mark.asyncio
async def test_guard_does_not_compare_processing_time(mock_session, handler_name, event_type):
    """`completed_at` is bound to now() — it must not appear in the guard predicate."""
    import src.handlers.outcomes as outcomes

    await getattr(outcomes, handler_name)(_make_call_event(event_type), mock_session)
    sql, params = _interaction_upsert(mock_session)
    guard = _normalize(sql).split("ON CONFLICT")[1]
    where = guard.split("WHERE")[1]

    assert "completed_at" not in where
    assert "started_at" not in where
    # The guard column is bound from the envelope, not from the clock.
    assert params["event_at"] != params["now"]


@pytest.mark.parametrize(
    "handler_name,event_type", [("handle_call_completed", "call.completed"), ("handle_call_missed", "call.missed")]
)
@pytest.mark.asyncio
async def test_dedup_predicate_is_not_used_as_the_guard(mock_session, handler_name, event_type):
    """`last_event_id IS DISTINCT FROM` prevents a duplicate, not a stale overwrite."""
    import src.handlers.outcomes as outcomes

    await getattr(outcomes, handler_name)(_make_call_event(event_type), mock_session)
    sql, _ = _interaction_upsert(mock_session)

    assert "IS DISTINCT FROM" not in _normalize(sql)


@pytest.mark.parametrize(
    "handler_name,event_type", [("handle_call_completed", "call.completed"), ("handle_call_missed", "call.missed")]
)
@pytest.mark.asyncio
async def test_handler_rejects_an_envelope_without_event_time(mock_session, handler_name, event_type):
    """An unorderable event fails loudly and writes nothing, so it redelivers/dead-letters."""
    import src.handlers.outcomes as outcomes

    event = _make_call_event(event_type)
    del event["timestamp"]

    with pytest.raises(ValueError, match="no timestamp"):
        await getattr(outcomes, handler_name)(event, mock_session)
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_outcome_row_insert_is_unchanged(mock_session):
    """The outcomes rows are immutable (DO NOTHING) — order-tolerant, no guard needed."""
    from src.handlers.outcomes import handle_call_completed

    await handle_call_completed(_make_call_event("call.completed"), mock_session)
    args, _ = mock_session.execute.call_args_list[1]
    sql = _normalize(args[0].text)

    assert "INSERT INTO outcomes" in sql
    assert "ON CONFLICT (outcome_id) DO NOTHING" in sql
