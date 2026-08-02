"""Tests for the slack-bot sequence guard (task 3.5, DNA-742).

Delivery is unordered once the transport is EventBridge + SQS. `chat_update`
leaves the system and is not undoable by a later event, so a stale update must
be dropped rather than applied.

Two layers are covered here:

* the compare-and-swap itself, on `ThreadManager` — that it compares the
  event-time column and never a processing-time value; and
* the lifecycle outcome, on the consumer handlers — that `created` →
  `updated` → `resolved` delivered in any order leaves the same terminal Slack
  text as in-order delivery.

The lifecycle tests drive the real handlers against an in-memory
`ThreadManager` double that applies the same ordering rule the SQL statement
applies. The SQL statement's own correctness is pinned by `TestAdvanceSequence`
below; no Postgres is available in this gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.consumer import (
    ParentMessageNotReady,
    handle_ticket_created,
    handle_ticket_resolved,
    handle_ticket_updated,
)
from src.thread_manager import ThreadManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_slack_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


def _session_maker_with_rowcount(rowcount: int):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(return_value=MagicMock(rowcount=rowcount))
    session.commit = AsyncMock()
    return MagicMock(return_value=session), session


def _executed_sql(session) -> str:
    return str(session.execute.call_args[0][0])


# ---------------------------------------------------------------------------
# ThreadManager.advance_*_sequence — the compare-and-swap
# ---------------------------------------------------------------------------


class TestAdvanceSequence:
    """The guard is one atomic UPDATE comparing the stored event time."""

    async def test_advances_when_event_is_newer(self, mock_slack_client):
        maker, session = _session_maker_with_rowcount(1)
        tm = ThreadManager(mock_slack_client, maker)

        assert await tm.advance_ticket_sequence("tkt-1", "2026-03-13T10:00:00Z") is True
        session.commit.assert_awaited_once()

    async def test_does_not_advance_when_event_is_older(self, mock_slack_client):
        maker, _session = _session_maker_with_rowcount(0)
        tm = ThreadManager(mock_slack_client, maker)

        assert await tm.advance_ticket_sequence("tkt-1", "2026-03-13T09:00:00Z") is False

    async def test_compares_the_event_time_column(self, mock_slack_client):
        maker, session = _session_maker_with_rowcount(1)
        tm = ThreadManager(mock_slack_client, maker)

        await tm.advance_ticket_sequence("tkt-1", "2026-03-13T10:00:00Z")

        sql = _executed_sql(session)
        assert "last_event_at < :event_ts" in sql

    async def test_never_compares_processing_time(self, mock_slack_client):
        """A guard comparing a processing-time value re-encodes the bug it fixes."""
        maker, session = _session_maker_with_rowcount(1)
        tm = ThreadManager(mock_slack_client, maker)

        await tm.advance_ticket_sequence("tkt-1", "2026-03-13T10:00:00Z")

        predicate = _executed_sql(session).split("WHERE", 1)[1]
        assert "now()" not in predicate
        assert "updated_at" not in predicate

    async def test_binds_the_parsed_event_time(self, mock_slack_client):
        maker, session = _session_maker_with_rowcount(1)
        tm = ThreadManager(mock_slack_client, maker)

        await tm.advance_ticket_sequence("tkt-1", "2026-03-13T10:00:00Z")

        params = session.execute.call_args[0][1]
        assert params["event_ts"] == datetime(2026, 3, 13, 10, 0, tzinfo=UTC)

    async def test_keys_task_sequence_on_task_id(self, mock_slack_client):
        maker, session = _session_maker_with_rowcount(1)
        tm = ThreadManager(mock_slack_client, maker)

        await tm.advance_task_sequence("task-1", "2026-03-13T10:00:00Z")

        sql = _executed_sql(session)
        assert "task_id = :key" in sql
        assert session.execute.call_args[0][1]["key"] == "task-1"

    @pytest.mark.parametrize("event_ts", [None, "", "not-a-timestamp"])
    async def test_fails_open_without_a_usable_event_time(self, mock_slack_client, event_ts):
        """No event time means no ordering signal — apply, but never write a fake one."""
        maker, session = _session_maker_with_rowcount(1)
        tm = ThreadManager(mock_slack_client, maker)

        assert await tm.advance_ticket_sequence("tkt-1", event_ts) is True
        session.execute.assert_not_awaited()


class TestUpdateParentStatusGuard:
    """The task-side parent header is guarded by the same compare-and-swap."""

    @staticmethod
    def _maker(rowcount: int):
        row = MagicMock(channel="#ocean-critical", message_ts="111.222")
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=row), rowcount=rowcount))
        session.commit = AsyncMock()
        return MagicMock(return_value=session)

    async def test_applies_when_event_is_newest(self, mock_slack_client):
        tm = ThreadManager(mock_slack_client, self._maker(1))

        await tm.update_parent_status("task-1", "RESOLVED", event_ts="2026-03-13T10:20:00Z")

        mock_slack_client.chat_update.assert_awaited_once()

    async def test_drops_a_stale_status(self, mock_slack_client):
        tm = ThreadManager(mock_slack_client, self._maker(0))

        await tm.update_parent_status("task-1", "CLAIMED", event_ts="2026-03-13T10:05:00Z")

        mock_slack_client.chat_update.assert_not_awaited()


# ---------------------------------------------------------------------------
# In-memory ThreadManager double for the lifecycle tests
# ---------------------------------------------------------------------------


class FakeThreadManager:
    """ThreadManager surface backed by a dict, applying the same ordering rule."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.thread_replies: list[dict] = []

    @staticmethod
    def _parse(event_ts):
        return datetime.fromisoformat(event_ts.replace("Z", "+00:00"))

    async def store_ticket_parent(self, ticket_id, channel, message_ts, event_ts=None) -> None:
        self.rows[ticket_id] = {
            "channel": channel,
            "message_ts": message_ts,
            "thread_ts": message_ts,
            "last_event_at": self._parse(event_ts) if event_ts else None,
        }

    async def get_ticket_channel(self, ticket_id):
        row = self.rows.get(ticket_id)
        return row["channel"] if row else None

    async def get_ticket_message_ts(self, ticket_id):
        row = self.rows.get(ticket_id)
        return row["message_ts"] if row else None

    async def get_ticket_thread_ts(self, ticket_id):
        row = self.rows.get(ticket_id)
        return row["thread_ts"] if row else None

    async def advance_ticket_sequence(self, ticket_id, event_ts) -> bool:
        row = self.rows.get(ticket_id)
        if row is None or not event_ts:
            return True
        incoming = self._parse(event_ts)
        stored = row["last_event_at"]
        if stored is not None and stored >= incoming:
            return False
        row["last_event_at"] = incoming
        return True

    async def queue_ticket_update(self, ticket_id, update) -> None:
        self.thread_replies.append({"ticket_id": ticket_id, **update})


CREATED = {
    "event_type": "ticket.created",
    "entity_id": "tkt-001",
    "timestamp": "2026-03-13T10:00:00Z",
    "payload": {
        "ticket_id": "tkt-001",
        "human_id": "DEV-00042",
        "category": "device_issue",
        "priority": "high",
        "patient_id": "patient-xyz",
        "description": "Device not syncing",
        "status": "open",
        "channel": "#device-issues",
    },
}

UPDATED = {
    "event_type": "ticket.updated",
    "entity_id": "tkt-001",
    "timestamp": "2026-03-13T10:05:00Z",
    "payload": {"ticket_id": "tkt-001", "status": "in_progress", "priority": "high"},
}

RESOLVED = {
    "event_type": "ticket.resolved",
    "entity_id": "tkt-001",
    "timestamp": "2026-03-13T10:20:00Z",
    "payload": {"ticket_id": "tkt-001", "status": "resolved", "resolved_by": "nurse-1"},
}

HANDLERS = {
    "ticket.created": handle_ticket_created,
    "ticket.updated": handle_ticket_updated,
    "ticket.resolved": handle_ticket_resolved,
}


async def _deliver(events, slack_client, thread_manager, *, redeliver=False):
    """Run events through their handlers, mimicking the consumer's commit-on-success loop."""
    pending = list(events)
    for _attempt in range(3):
        deferred = []
        for event in pending:
            try:
                await HANDLERS[event["event_type"]](
                    event,
                    slack_client=slack_client,
                    session_maker=MagicMock(),
                    hasura_url="http://hasura",
                    publisher=AsyncMock(),
                    thread_manager=thread_manager,
                )
            except ParentMessageNotReady:
                if not redeliver:
                    raise
                deferred.append(event)
        if not deferred:
            return
        pending = deferred
    raise AssertionError("events never became deliverable")


def _terminal_card_text(slack_client) -> str:
    return slack_client.chat_update.call_args_list[-1].kwargs["text"]


# ---------------------------------------------------------------------------
# Lifecycle: out-of-order delivery reaches the in-order terminal state
# ---------------------------------------------------------------------------


@pytest.fixture()
def summary(monkeypatch):
    import src.consumer as consumer_module

    monkeypatch.setattr(
        consumer_module,
        "generate_summary_with_context",
        AsyncMock(return_value=("AI summary text", [])),
    )


class TestOutOfOrderLifecycle:
    async def test_reversed_updates_leave_the_resolved_card(self, summary, mock_slack_client):
        """created → resolved → updated ends on the resolved card, not the update."""
        tm = FakeThreadManager()
        await _deliver([CREATED, RESOLVED, UPDATED], mock_slack_client, tm)

        assert _terminal_card_text(mock_slack_client) == "Ticket tkt-001 resolved"

    async def test_matches_in_order_terminal_text(self, summary, mock_slack_client):
        in_order_client = mock_slack_client
        await _deliver([CREATED, UPDATED, RESOLVED], in_order_client, FakeThreadManager())
        in_order_text = _terminal_card_text(in_order_client)

        out_of_order_client = AsyncMock()
        out_of_order_client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234.5678"})
        out_of_order_client.chat_update = AsyncMock(return_value={"ok": True})
        await _deliver([CREATED, RESOLVED, UPDATED], out_of_order_client, FakeThreadManager())

        assert _terminal_card_text(out_of_order_client) == in_order_text

    async def test_stale_update_issues_no_external_update(self, summary, mock_slack_client):
        tm = FakeThreadManager()
        await _deliver([CREATED, RESOLVED], mock_slack_client, tm)
        updates_before = mock_slack_client.chat_update.call_count

        await _deliver([UPDATED], mock_slack_client, tm)

        assert mock_slack_client.chat_update.call_count == updates_before

    async def test_stale_update_still_records_the_thread_reply(self, summary, mock_slack_client):
        """Dropping the card update must not drop the append-only thread trail."""
        tm = FakeThreadManager()
        await _deliver([CREATED, RESOLVED, UPDATED], mock_slack_client, tm)

        assert any(reply["type"] == "status_change" for reply in tm.thread_replies)

    async def test_update_before_create_is_redelivered_not_dropped(self, summary, mock_slack_client):
        """No parent yet means the event is not yet processable — leave it for redelivery."""
        tm = FakeThreadManager()

        with pytest.raises(ParentMessageNotReady):
            await _deliver([UPDATED], mock_slack_client, tm)

    async def test_fully_reversed_lifecycle_converges(self, summary, mock_slack_client):
        """resolved → updated → created, with redelivery, still ends resolved."""
        tm = FakeThreadManager()
        await _deliver([RESOLVED, UPDATED, CREATED], mock_slack_client, tm, redeliver=True)

        assert _terminal_card_text(mock_slack_client) == "Ticket tkt-001 resolved"
