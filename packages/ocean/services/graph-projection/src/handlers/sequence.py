"""Event-time sequence guard shared by the graph-projection handlers.

Delivery is unordered. Any projection that overwrites a mutable column must
therefore compare the *event* time of the incoming event against the event time
of whatever last wrote the row, and drop the write when it is stale.

Two rules this module exists to enforce:

1. **Never guard on processing time.** A column populated with
   ``datetime.now()`` — ``interactions.completed_at``, for one — encodes
   *arrival* order under reordering, so guarding on it re-encodes the bug the
   guard exists to fix.
2. **Never guard on the event identifier alone.** ``last_event_id IS DISTINCT
   FROM`` suppresses a duplicate of the same event; it does nothing about a
   different, older event arriving after a newer one.

The comparison is a row comparison over ``(last_event_at, last_event_id)``.
``last_event_at`` decides; ``last_event_id`` is only a tiebreak, so two distinct
events sharing an envelope timestamp still converge on one deterministic winner
regardless of arrival order. Re-delivering the event that already wrote the row
compares equal, not greater, so it is a no-op — idempotent under at-least-once.
"""

from __future__ import annotations

from datetime import UTC, datetime


def event_time(event_data: dict) -> datetime:
    """Return the envelope's event time as a timezone-aware datetime.

    Raises:
        ValueError: the envelope carries no timestamp, or one that cannot be
            parsed. An event with no event time cannot be ordered, and falling
            back to the clock would silently reintroduce arrival-order
            semantics — so the handler fails and the message is redelivered or
            dead-lettered rather than corrupting state.
    """
    raw = event_data.get("timestamp")

    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str) and raw:
        text = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"event envelope carries an unparseable timestamp: {raw!r}") from exc
    else:
        raise ValueError("event envelope carries no timestamp; the write cannot be ordered")

    # The envelope declares UTC ISO 8601; a naive value is UTC that lost its suffix.
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def sequence_guard(
    table: str,
    at_column: str = "last_event_at",
    id_column: str = "last_event_id",
) -> str:
    """Return the ``WHERE`` clause qualifying an ``ON CONFLICT ... DO UPDATE``.

    The ``IS NULL`` branch is load-bearing: rows written before the guard column
    existed, or by a handler that does not yet set it, hold NULL. A bare
    ``EXCLUDED.last_event_at > table.last_event_at`` evaluates to NULL against
    those rows, which Postgres treats as false — silently dropping every update
    to them.
    """
    return (
        f"WHERE {table}.{at_column} IS NULL "
        f"   OR (EXCLUDED.{at_column}, EXCLUDED.{id_column}) "
        f"    > ({table}.{at_column}, {table}.{id_column})"
    )
