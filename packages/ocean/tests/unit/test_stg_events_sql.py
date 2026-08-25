"""STG_EVENTS.EVENTS view (snowflake-projection task 1.1) — offline, no live Snowflake.

Parses the committed `stg_events_events.sql` and asserts its shape: the dedupe rule, the
work order's pinned minimum columns, no `_topic` filter, and — the emitter-comparison test —
that every field `pulse_ledger.relay._envelope` actually puts on the wire has a matching
column, so the view can never silently drift behind what the relay emits.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pulse_ledger.relay import _envelope

_SQL_PATH = Path(__file__).resolve().parents[2] / "infra" / "snowflake" / "stg_events_events.sql"

#: The work order's pinned floor — every one of these must appear as an output column,
#: regardless of what else the emitter adds.
_MINIMUM_COLUMNS = frozenset({
    "event_id",
    "event_type",
    "subject_type",
    "subject_key",
    "seq",
    "effective_at",
    "_topic",
    "_loaded_at",
})

#: `EventBridgePublisher.publish` (ocean_broker.publisher) adds this field to every envelope it
#: is given a routing key for, after `_envelope` builds it — the relay always passes one
#: (`PendingRow.routing_key`), so it always lands on the bus alongside `_envelope`'s own fields.
_PUBLISHER_ADDED_FIELDS = frozenset({"key"})


def _sql_text() -> str:
    return _SQL_PATH.read_text()


def _select_columns(sql: str) -> list[str]:
    """Output column names, in order, parsed from the `SELECT ... FROM` list.

    Each line is either `<expr> AS <name>` or a bare passthrough column (`_topic`,
    `_loaded_at`); both forms are handled without a full SQL parser because this file's shape
    is committed and simple by design (design.md decision 3).
    """
    select_block = sql.split("SELECT", 1)[1].split("\nFROM ", 1)[0]
    columns = []
    for raw_line in select_block.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        match = re.search(r'\bAS\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s*$', line, re.IGNORECASE)
        columns.append(match.group(1) if match else line.strip('"'))
    return columns


def _fake_outbox_row() -> dict[str, Any]:
    """A synthetic joined outbox/events row shaped exactly like `_SELECT_PENDING_SQL` returns.

    Values are synthetic, never PHI (repo-wide posture) — only the field *names* matter here.
    """
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    return {
        "event_id": uuid.uuid4(),
        "event_type": "patient.admitted",
        "subject_type": "patient",
        "subject_key": "synthetic-subject-1",
        "seq": 1,
        "effective_at": now,
        "recorded_at": now,
        "producer": "pulse-ledger",
        "schema_version": 1,
        "rule_version": "v1",
        "correlation_id": uuid.uuid4(),
        "causation_id": None,
        "reverses_event_id": None,
        "actor_type": "system",
        "actor_id": "relay-test",
        "actor_authority": None,
        "evidence": {"kind": "synthetic"},
        "evidence_class": "E0",
        "epoch": "declared",
        "payload": {"synthetic": True},
    }


def test_qualify_dedupe_orders_by_loaded_at_ascending() -> None:
    sql = _sql_text()
    assert "QUALIFY ROW_NUMBER() OVER (PARTITION BY data:event_id ORDER BY _loaded_at ASC) = 1" in sql


def test_minimum_columns_are_present() -> None:
    columns = set(_select_columns(_sql_text()))
    missing = _MINIMUM_COLUMNS - columns
    assert not missing, f"missing pinned minimum column(s): {sorted(missing)}"


def test_no_topic_filter() -> None:
    sql = _sql_text()
    assert "WHERE" not in sql.upper(), "STG_EVENTS.EVENTS must not filter by topic — consumers filter on _topic"


def test_every_emitted_field_has_a_matching_column() -> None:
    """The columns match the emitter (scenario in specs/snowflake-stg-events/spec.md)."""
    envelope = _envelope(_fake_outbox_row())
    emitted_fields = set(envelope.keys()) | _PUBLISHER_ADDED_FIELDS
    columns = set(_select_columns(_sql_text()))
    missing = emitted_fields - columns
    assert not missing, f"emitter produces field(s) with no matching STG_EVENTS.EVENTS column: {sorted(missing)}"
