"""Executable evidence for control-plane's per-handler ordering verdict (task 3.6, DNA-743).

The design audit recorded control-plane as "order-tolerant, per handler, to be re-confirmed per
handler during conversion". This module is that re-confirmation: one assertion per claim in
`packages/ocean/docs/ordering-verdict-control-plane.md`, so the recorded verdict cannot drift
from the code without a test going red.

Three shapes appear here:

- **Tolerance proofs** — drive a handler's events in both orders and assert the effect is the
  same. These pass today and lock the verdict.
- **`xfail(strict=True)` claims** — the property the spec requires, written in canonical form,
  currently unmet. Each names the follow-up task that makes it pass; when that task lands, strict
  xfail turns the test red until the marker is removed. That is the forcing function.
- **Characterisation tests** — behaviour that is order-dependent but not fixable with a sequence
  guard (an event dropped because its precondition row has not arrived yet). They pin what the
  code does today so the follow-up task changes it deliberately.

No broker and no database: the handlers' only state input is what they read back from `session`,
so a recording session double that models the two columns they actually read is a faithful stand-in
and keeps this runnable in CI once services join the test scope (DNA-779).
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

# Allow importing src package from service root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

VERDICT_DOC = Path(__file__).resolve().parents[3] / "docs" / "ordering-verdict-control-plane.md"

ORDER_TOLERANT = "Order-tolerant"
ORDER_DEPENDENT = "Order-dependent"


# ---------------------------------------------------------------------------
# Session double
# ---------------------------------------------------------------------------


class _Result:
    """Stands in for a SQLAlchemy Result over the handful of accessors the handlers use."""

    def __init__(self, value: Any = None, row: Any = None, rowcount: int = 1) -> None:
        self._value = value
        self._row = row
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value if self._value is not None else 0

    def fetchone(self) -> Any:
        return self._row


class RecordingSession:
    """Records every statement and answers reads from an explicit `rows` dict.

    Only the reads the control-plane handlers actually perform are modelled. Anything else
    answers empty, which is what an unpopulated database would do.
    """

    def __init__(self, **rows: Any) -> None:
        self.rows: dict[str, Any] = rows
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, clause: Any, params: dict | None = None) -> _Result:
        sql = " ".join(str(clause).split())
        params = params or {}
        self.statements.append((sql, params))

        if sql.startswith("UPDATE tickets SET") and "status = :new_status" in sql:
            # Model the event-time sequence guard the way Postgres evaluates it:
            # a write whose event time is not strictly newer updates zero rows.
            guarded = "last_event_at IS NULL OR last_event_at < :event_at" in sql
            last_event_at = self.rows.get("ticket_last_event_at")
            if guarded and last_event_at is not None and params["event_at"] <= last_event_at:
                return _Result(rowcount=0)
            self.rows["ticket_status"] = params["new_status"]
            if guarded:
                self.rows["ticket_last_event_at"] = params["event_at"]
            return _Result()
        if sql.startswith("SELECT status FROM tickets"):
            return _Result(value=self.rows.get("ticket_status"))
        if sql.startswith("SELECT patient_id, category FROM tickets"):
            return _Result(row=self.rows.get("ticket_row"))
        if sql.startswith("SELECT ticket_id FROM returns"):
            return _Result(value=self.rows.get("return_ticket_id"))
        if sql.startswith("SELECT nextval"):
            return _Result(value=self.rows.get("nextval", 1))
        if sql.startswith("SELECT snooze_until FROM alert_snoozes"):
            return _Result(row=self.rows.get("snooze_row"))
        if sql.startswith("SELECT COUNT(*) FILTER"):
            return _Result(row=self.rows.get("fp_row"))
        return _Result()

    def sql_matching(self, needle: str) -> list[tuple[str, dict]]:
        return [(sql, params) for sql, params in self.statements if needle in sql]

    def mutations(self) -> list[tuple[str, dict]]:
        return [
            (sql, params)
            for sql, params in self.statements
            if sql.split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
        ]


class RecordingProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, topic: str, event: dict) -> None:
        self.published.append((topic, event))


def _stable(published: list[tuple[str, dict]]) -> set[tuple]:
    """Reduce published events to their order-independent content.

    `event_id` is a fresh uuid4 per emission and `timestamp` is stamped at processing time, so
    neither says anything about whether the effect depended on delivery order. Everything that
    identifies the effect — topic, type, subject entity, payload — is kept.
    """
    return {
        (
            topic,
            event["event_type"],
            event["entity_id"],
            repr(sorted(event["payload"].items(), key=lambda kv: kv[0])),
        )
        for topic, event in published
    }


def _event(event_type: str, entity_id: str = "", timestamp: str = "2026-03-11T10:00:00Z", **payload: Any) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": timestamp,
        "source_system": "test",
        "entity_id": entity_id,
        "entity_type": "test",
        "correlation_id": "corr-3-6",
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# The verdict record itself
# ---------------------------------------------------------------------------


def _verdict_table() -> dict[str, str]:
    """Parse `| \\`event.type\\` | \\`handler\\` | Verdict | … |` rows out of the verdict doc."""
    row = re.compile(r"^\|\s*`([a-z.]+)`\s*\|\s*`(\w+)`\s*\|\s*([A-Za-z-]+)\s*\|")
    verdicts: dict[str, str] = {}
    for line in VERDICT_DOC.read_text().splitlines():
        match = row.match(line)
        if match:
            verdicts[match.group(1)] = match.group(3)
    return verdicts


def test_verdict_doc_exists():
    """The audit's output is a committed record, not a review comment."""
    assert VERDICT_DOC.is_file(), f"missing verdict record at {VERDICT_DOC}"


def test_every_event_handler_has_a_recorded_verdict():
    """Every key in EVENT_HANDLERS carries a verdict, and the record names no key that is gone."""
    from src.consumer import EVENT_HANDLERS

    verdicts = _verdict_table()
    assert set(verdicts) == set(EVENT_HANDLERS), (
        f"unrecorded: {sorted(set(EVENT_HANDLERS) - set(verdicts))}; "
        f"stale: {sorted(set(verdicts) - set(EVENT_HANDLERS))}"
    )


def test_every_verdict_is_one_of_the_two_allowed_values():
    """`event-delivery` admits exactly two verdicts. 'Probably fine' is not one of them."""
    verdicts = _verdict_table()
    assert verdicts
    assert set(verdicts.values()) <= {ORDER_TOLERANT, ORDER_DEPENDENT}


def test_the_verdict_doc_names_the_handler_each_event_type_routes_to():
    """The record's handler column matches the wiring it describes."""
    from src.consumer import EVENT_HANDLERS

    row = re.compile(r"^\|\s*`([a-z.]+)`\s*\|\s*`(\w+)`\s*\|")
    named = {m.group(1): m.group(2) for m in (row.match(line) for line in VERDICT_DOC.read_text().splitlines()) if m}
    for event_type, handler in EVENT_HANDLERS.items():
        assert named[event_type] == handler.__name__


# ---------------------------------------------------------------------------
# Order-tolerant: the outcome relays
# ---------------------------------------------------------------------------


class TestOutcomeRelaysAreOrderTolerant:
    """`alert.resolved`, `task.completed`, `call.completed`, `call.missed`.

    Each reads nothing, writes nothing, and emits one `outcome.recorded` whose id is
    `uuid5(entity_id, resolution_type)`. Reordering cannot change the set of emissions.
    """

    async def test_competing_call_outcomes_emit_the_same_set_in_either_order(self):
        from src.handlers.outcomes import handle_call_completed, handle_call_missed

        engagement = "engagement-3-6"
        completed = _event("call.completed", engagement, "2026-03-11T10:00:00Z", agent_id="agent-1")
        missed = _event("call.missed", engagement, "2026-03-11T10:05:00Z", agent_id="agent-1")

        forward = RecordingProducer()
        session = RecordingSession()
        await handle_call_completed(completed, session, producer=forward)
        await handle_call_missed(missed, session, producer=forward)

        reverse = RecordingProducer()
        session_reverse = RecordingSession()
        await handle_call_missed(missed, session_reverse, producer=reverse)
        await handle_call_completed(completed, session_reverse, producer=reverse)

        assert _stable(forward.published) == _stable(reverse.published)
        assert session.mutations() == []
        assert session_reverse.mutations() == []

    async def test_outcome_ids_are_deterministic_so_a_redelivery_is_a_duplicate_not_a_new_outcome(self):
        from src.handlers.outcomes import handle_task_completed

        event = _event("task.completed", "task-3-6", persona_id="nurse-1")
        first, second = RecordingProducer(), RecordingProducer()
        await handle_task_completed(event, RecordingSession(), producer=first)
        await handle_task_completed(event, RecordingSession(), producer=second)

        assert first.published[0][1]["entity_id"] == second.published[0][1]["entity_id"]

    async def test_the_relay_carries_the_source_event_time_forward(self):
        """The downstream guard in task 3.1 needs an event-time field; these four supply it."""
        from src.handlers.outcomes import (
            handle_alert_resolved,
            handle_call_completed,
            handle_call_missed,
            handle_task_completed,
        )

        event_time = "2026-03-11T09:30:00Z"
        for handler, event_type in (
            (handle_alert_resolved, "alert.resolved"),
            (handle_task_completed, "task.completed"),
            (handle_call_completed, "call.completed"),
            (handle_call_missed, "call.missed"),
        ):
            producer = RecordingProducer()
            await handler(_event(event_type, "entity-3-6", event_time), RecordingSession(), producer=producer)
            _, emitted = producer.published[0]
            assert emitted["timestamp"] == event_time, event_type
            assert emitted["payload"]["resolved_at"] == event_time, event_type


# ---------------------------------------------------------------------------
# Order-tolerant: heartbeats, alert.created, ticket creation
# ---------------------------------------------------------------------------


class TestHeartbeatIsOrderTolerant:
    """`connector.heartbeat` — order-tolerant by erasure: it stores processing time, not event time."""

    async def test_stored_last_seen_ignores_the_event_timestamp(self):
        from src.handlers.heartbeats import handle_connector_heartbeat

        session = RecordingSession()
        await handle_connector_heartbeat(
            _event("connector.heartbeat", "c1", "2020-01-01T00:00:00Z", connector_id="c1", connector_name="c1"),
            session,
        )

        (sql, params) = session.sql_matching("INSERT INTO connector_health")[0]
        assert "ON CONFLICT (connector_id) DO UPDATE" in sql
        assert params["last_seen"].year >= 2026, "last_seen is processing time, so a stale heartbeat cannot rewind it"

    async def test_liveness_is_the_only_state_written(self):
        from src.handlers.heartbeats import handle_connector_heartbeat

        session = RecordingSession()
        await handle_connector_heartbeat(_event("connector.heartbeat", "c1", connector_id="c1"), session)
        assert len(session.mutations()) == 1


class TestAlertCreatedIsOrderTolerant:
    """`alert.created` — the task row's substantive columns are fixed by first arrival."""

    async def test_conflict_clause_updates_bookkeeping_columns_only(self):
        from src.handlers.alerts import handle_alert_created

        session = RecordingSession()
        await handle_alert_created(
            _event("alert.created", "alert-3-6", patient_id="patient-1", alert_type="glucose"),
            session,
        )

        (sql, _params) = session.sql_matching("INSERT INTO tasks")[0]
        conflict = sql.split("ON CONFLICT (task_id) DO UPDATE SET", 1)[1]
        updated = {c.strip().split(" ")[0] for c in conflict.split("WHERE", 1)[0].split(",")}
        assert updated == {"updated_at", "last_event_id"}, (
            "status, priority and task_type must not be rewritable by a later-arriving duplicate"
        )

    async def test_task_id_is_derived_from_the_alert_so_redelivery_cannot_fork_the_row(self):
        from src.handlers.alerts import handle_alert_created

        ids = []
        for _ in range(2):
            session = RecordingSession()
            await handle_alert_created(_event("alert.created", "alert-3-6", patient_id="p"), session)
            ids.append(session.sql_matching("INSERT INTO tasks")[0][1]["task_id"])
        assert ids[0] == ids[1]

    async def test_escalation_tracking_insert_is_conflict_free(self):
        from src.handlers.alerts import handle_alert_created

        session = RecordingSession()
        await handle_alert_created(_event("alert.created", "alert-3-6", patient_id="p"), session)
        (sql, _params) = session.sql_matching("INSERT INTO task_escalation_state")[0]
        assert "DO NOTHING" in sql


class TestTicketCreationIsOrderTolerant:
    """`ticket.create.requested` / `ticket.created` — each event writes its own row."""

    async def test_no_prior_ticket_state_is_read(self):
        from src.handlers.tickets import handle_ticket_created

        session = RecordingSession()
        await handle_ticket_created(_event("ticket.create.requested", "", category="device_issue"), session)
        assert session.sql_matching("SELECT status FROM tickets") == []
        assert session.sql_matching("SELECT patient_id, category FROM tickets") == []

    async def test_each_delivery_writes_a_distinct_ticket_id(self):
        """Not an ordering property — the duplicate hazard this exposes is recorded separately."""
        from src.handlers.tickets import handle_ticket_created

        ids = []
        for _ in range(2):
            session = RecordingSession()
            await handle_ticket_created(_event("ticket.create.requested", "", category="device_issue"), session)
            ids.append(session.sql_matching("INSERT INTO tickets")[0][1]["ticket_id"])
        assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# Order-dependent: the ticket state machine
# ---------------------------------------------------------------------------


class TestTicketUpdatedIsGuardedOnEventTime:
    """`ticket.update.requested` / `ticket.updated` — event-time sequence guard, task 3.7.

    The status write carries a monotonic predicate on `tickets.last_event_at`, populated from
    the envelope `timestamp` (migration 0020). `is_valid_transition` stays as request
    validation; ordering protection comes from the guard. Each event below carries the
    timestamp of its lifecycle position, so "reversed" means the same events delivered
    backwards — not a different history.
    """

    async def _drive(self, events: list[tuple[str, str]]) -> tuple[RecordingSession, RecordingProducer]:
        from src.handlers.tickets import handle_ticket_updated

        session = RecordingSession(ticket_status="open")
        producer = RecordingProducer()
        for status, timestamp in events:
            event = _event("ticket.update.requested", "ticket-3-6", timestamp, new_status=status)
            await handle_ticket_updated(event, session, producer=producer)
        return session, producer

    async def test_the_status_write_carries_an_event_time_sequence_guard(self):
        session, _producer = await self._drive([("in_progress", "2026-03-11T10:00:00Z")])
        (sql, params) = session.sql_matching("UPDATE tickets SET")[0]
        assert "last_event_at IS NULL OR last_event_at < :event_at" in sql
        assert "updated_at <" not in sql, "processing time must never be the guard column (Caveat A)"
        assert params["event_at"].isoformat() == "2026-03-11T10:00:00+00:00"

    async def test_reversed_lifecycle_reaches_the_same_terminal_status(self):
        """`event-delivery`: out-of-order delivery must reach the state in-order delivery reaches.

        `waiting ↔ in_progress` are both legal, so before 3.7 the terminal status inside the
        working states was whichever event was processed last. The guard drops the stale one.
        """
        lifecycle = [("waiting", "2026-03-11T10:00:00Z"), ("in_progress", "2026-03-11T11:00:00Z")]
        in_order, _ = await self._drive(lifecycle)
        reversed_order, _ = await self._drive(list(reversed(lifecycle)))
        assert in_order.rows["ticket_status"] == "in_progress"
        assert reversed_order.rows["ticket_status"] == in_order.rows["ticket_status"]

    async def test_a_stale_event_publishes_nothing(self):
        """A dropped write must not re-announce the old status downstream (blast radius: slack-bot)."""
        lifecycle = [("waiting", "2026-03-11T10:00:00Z"), ("in_progress", "2026-03-11T11:00:00Z")]
        _, producer = await self._drive(list(reversed(lifecycle)))
        announced = [event["payload"]["status"] for _topic, event in producer.published]
        assert announced == ["in_progress"], "the stale `waiting` event must not be published"

    async def test_a_late_earlier_event_does_not_overwrite_a_resolved_ticket(self):
        """`resolved` is a sink in VALID_TRANSITIONS, so the terminal state alone is protected.

        Before 3.7 this was the one thing the state machine bought; the guard now enforces the
        same outcome one layer lower.
        """
        from src.handlers.tickets import handle_ticket_updated

        session = RecordingSession(ticket_status="waiting")
        await handle_ticket_updated(
            _event("ticket.update.requested", "ticket-3-6", "2026-03-11T12:00:00Z", new_status="resolved"),
            session,
        )
        await handle_ticket_updated(
            _event("ticket.update.requested", "ticket-3-6", "2026-03-11T11:00:00Z", new_status="in_progress"),
            session,
        )
        assert session.rows["ticket_status"] == "resolved"

    async def test_an_early_resolved_event_is_still_dropped_by_the_legality_check(self):
        """Characterisation, not endorsement: a `resolved` that outruns its `in_progress` is lost.

        From `open`, `resolved` is an illegal transition, so the legality check drops it before
        the guarded write is ever attempted — the same precondition-drop class as Finding 2. A
        sequence guard cannot fix an event whose precondition has not arrived; that treatment
        (park or redeliver, against 6.3's DLQ design) is task 3.8's, and this pin changes when
        it is extended here.
        """
        lifecycle = [("in_progress", "2026-03-11T10:00:00Z"), ("resolved", "2026-03-11T11:00:00Z")]
        reversed_order, _ = await self._drive(list(reversed(lifecycle)))
        assert reversed_order.rows["ticket_status"] == "in_progress", "the early resolved event is silently lost today"

    async def test_the_ticket_outcome_relay_carries_event_time(self):
        from src.handlers.tickets import handle_ticket_updated

        event_time = "2026-03-11T09:30:00Z"
        session = RecordingSession(ticket_status="in_progress")
        producer = RecordingProducer()
        await handle_ticket_updated(
            _event("ticket.update.requested", "ticket-3-6", event_time, new_status="resolved"),
            session,
            producer=producer,
        )
        outcome = next(event for _topic, event in producer.published if event["event_type"] == "outcome.recorded")
        assert outcome["payload"]["resolved_at"] == event_time


# ---------------------------------------------------------------------------
# Order-dependent: precondition drops
# ---------------------------------------------------------------------------


class TestPreconditionDropsAreOrderDependent:
    """`ticket.rma.requested` and `return.updated` read a row another event creates.

    Arriving first, they are dropped and acknowledged. Redelivery never happens, so the effect is
    lost outright — a sequence guard cannot fix this; parking or retry can. Characterisation:
    these assertions pin today's behaviour and change when that follow-up lands.
    """

    async def test_rma_request_before_its_ticket_is_dropped_silently(self):
        from src.handlers.tickets import handle_rma_requested

        session = RecordingSession()  # no ticket_row: the ticket event has not been processed yet
        producer = RecordingProducer()
        await handle_rma_requested(
            _event("ticket.rma.requested", "ticket-3-6", reason="device failure"), session, producer=producer
        )

        assert producer.published == [], "no ticket.rma.failed either — the request vanishes"
        assert session.mutations() == []

    async def test_return_update_before_its_return_row_is_dropped_silently(self):
        from src.handlers.tickets import handle_return_status_update

        session = RecordingSession()  # no return_ticket_id: the RMA insert has not happened yet
        producer = RecordingProducer()
        await handle_return_status_update(
            _event("return.updated", "return-1", return_id="return-1", status="shipped"),
            session,
            producer=producer,
        )

        assert producer.published == []

    async def test_the_same_return_update_is_relayed_once_its_link_exists(self):
        """Same event, same handler, different arrival order — different outcome. That is the finding."""
        from src.handlers.tickets import handle_return_status_update

        session = RecordingSession(return_ticket_id="ticket-3-6")
        producer = RecordingProducer()
        await handle_return_status_update(
            _event("return.updated", "return-1", return_id="return-1", status="shipped"),
            session,
            producer=producer,
        )

        assert [event["event_type"] for _topic, event in producer.published] == ["ticket.rma.status"]


# ---------------------------------------------------------------------------
# Order-tolerant: delivery notification
# ---------------------------------------------------------------------------


class TestDeliveryNotificationIsOrderTolerant:
    """`fulfillment.updated` — reads context, writes nothing, publishes on `delivered` only."""

    async def test_writes_no_state(self):
        from src.handlers.deliveries import handle_delivery_notification

        session = RecordingSession()
        producer = RecordingProducer()
        await handle_delivery_notification(
            _event("fulfillment.updated", "order-1", status="delivered", patient_id="p", order_id="order-1"),
            session,
            producer=producer,
        )
        assert session.mutations() == []
        assert [event["event_type"] for _topic, event in producer.published] == ["delivery.notify"]

    async def test_non_delivered_statuses_are_skipped_in_any_order(self):
        from src.handlers.deliveries import handle_delivery_notification

        producer = RecordingProducer()
        for status in ("in_transit", "label_created"):
            await handle_delivery_notification(
                _event("fulfillment.updated", "order-1", status=status, patient_id="p"),
                RecordingSession(),
                producer=producer,
            )
        assert producer.published == []


# ---------------------------------------------------------------------------
# Not an ordering property, found while auditing the same wiring
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="control-plane consumes the ticket.created it publishes, so every ticket creates another (HANDOFF task 3.9)",
)
def test_no_handler_re_emits_an_event_type_this_consumer_handles():
    """A handler that publishes a type its own EVENT_HANDLERS accepts is a self-feeding cycle."""
    from src.consumer import EVENT_HANDLERS

    source = (Path(__file__).resolve().parents[1] / "src" / "handlers" / "tickets.py").read_text()
    emitted = set(re.findall(r'"event_type": "([a-z.]+)"', source))
    assert emitted & set(EVENT_HANDLERS) == set()
