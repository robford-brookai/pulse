"""Task 5.1 — end-to-end fold equivalence, against a real Postgres.

For each of the six ledger-owned subject types (object model v0.7), commits a mixed history —
forward, backdated, reversal, backfill — then re-derives state by folding the raw committed events
with nothing borrowed from the commit path's internal fold call, and asserts the result equals the
co-committed `current_state` row. This is the property `pulse_ledger.fold`'s docstring names as
task 5.1's obligation: the commit path, the read path, and the warehouse's independent
re-derivation share one ordering rule and must agree.

Also pins that every committed event carries the envelope-compatible columns the `ledger-record`
spec requires for the `STG_EVENTS` flat projection (`design/platform/snowflake-landing-spec.md`),
so a later migration cannot silently drop one without a test turning red.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_core.generated import CATALOG_VERSION
from pulse_ledger.commit import Declaration, commit_declaration, commit_reversal
from pulse_ledger.fold import FoldedEvent, fold_state, state_borne_by

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

#: One legal, branching-where-possible mixed history per subject type: an entry genesis, a second
#: forward transition, a backdated transition legal from the same entry state, and a non-entry
#: state a backfill can anchor a separate subject at. Computed from `pulse_core.generated.TRANSITIONS`
#: (appendix-c-v0.7) — where a catalog entry state has only one outgoing edge (`device`, `contract`),
#: the second and backdated transitions necessarily share a target; that is a real shape of those
#: catalogs, not a test artifact.
SCENARIOS: dict[str, dict[str, str]] = {
    "referral": {"entry": "received", "second": "resolved", "backdated": "closed", "backfill_anchor": "outreach"},
    "consent": {"entry": "requested", "second": "granted", "backdated": "granted", "backfill_anchor": "granted"},
    "enrollment": {"entry": "pending_start", "second": "active", "backdated": "ended", "backfill_anchor": "active"},
    "billing_episode": {
        "entry": "open",
        "second": "qualified",
        "backdated": "not_qualified",
        "backfill_anchor": "qualified",
    },
    "device": {"entry": "ordered", "second": "shipped", "backdated": "shipped", "backfill_anchor": "active"},
    "contract": {"entry": "draft", "second": "active", "backdated": "active", "backfill_anchor": "active"},
}

#: The `ledger-record` spec's envelope-compatible columns for the `STG_EVENTS` flat projection.
FLAT_PROJECTION_COLUMNS = (
    "event_id",
    "event_type",
    "subject_type",
    "subject_key",
    "effective_at",
    "recorded_at",
    "producer",
    "schema_version",
    "rule_version",
    "correlation_id",
    "causation_id",
    "actor_type",
    "actor_id",
    "actor_authority",
    "evidence",
    "payload",
)


def _declare(
    subject_type: str,
    subject_key: str,
    *,
    to_state: str | None,
    event_type: str,
    effective_at: datetime,
    **overrides: Any,
) -> Declaration:
    fields: dict[str, Any] = {
        "subject_type": subject_type,
        "subject_key": subject_key,
        "event_type": event_type,
        "to_state": to_state,
        "effective_at": effective_at,
        "actor_type": "system",
        "actor_id": "fold-equivalence-tests",
        "producer": "pulse-ledger-tests",
    }
    fields.update(overrides)
    return Declaration(**fields)


def _independent_fold(
    conn: psycopg.Connection, subject_type: str, subject_key: str
) -> tuple[str, datetime, uuid.UUID] | None:
    """Re-derive a subject's state from its raw committed rows, not from the commit path's fold.

    Mirrors what the warehouse does over `STG_EVENTS.EVENTS`: read every event for the subject,
    keep only what is state-bearing or a reversal, and fold with `pulse_ledger.fold.fold_state` —
    the one shared ordering rule, exercised here against event rows the test queried itself rather
    than through `pulse_ledger.commit.load_folded_events`.
    """
    rows = conn.execute(
        "SELECT event_id, payload, effective_at, recorded_at, reverses_event_id"
        " FROM ledger.events WHERE subject_type = %s AND subject_key = %s",
        (subject_type, subject_key),
    ).fetchall()
    events: list[FoldedEvent] = []
    for event_id, payload, effective_at, recorded_at, reverses_event_id in rows:
        to_state = state_borne_by(payload)
        if to_state is None and reverses_event_id is None:
            continue
        events.append(
            FoldedEvent(
                event_id=event_id,
                to_state=to_state or "",
                effective_at=effective_at,
                recorded_at=recorded_at,
                reverses_event_id=reverses_event_id,
            )
        )
    folded = fold_state(events)
    if folded is None:
        return None
    return (folded.state, folded.effective_at, folded.event_id)


def _stored_current_state(
    conn: psycopg.Connection, subject_type: str, subject_key: str
) -> tuple[str, datetime, uuid.UUID] | None:
    row = conn.execute(
        "SELECT state, effective_at, last_event_id FROM ledger.current_state"
        " WHERE subject_type = %s AND subject_key = %s",
        (subject_type, subject_key),
    ).fetchone()
    return row


@pytest.mark.parametrize("subject_type", sorted(SCENARIOS))
def test_independent_fold_equals_current_state_after_a_mixed_history(
    ledger_db: psycopg.Connection, subject_type: str
) -> None:
    scenario = SCENARIOS[subject_type]
    subject_key = "mix-1"

    forward = commit_declaration(
        ledger_db,
        _declare(
            subject_type,
            subject_key,
            to_state=scenario["entry"],
            event_type=f"{subject_type}.{scenario['entry']}",
            effective_at=T0,
        ),
    )
    second = commit_declaration(
        ledger_db,
        _declare(
            subject_type,
            subject_key,
            to_state=scenario["second"],
            event_type=f"{subject_type}.{scenario['second']}",
            effective_at=T0 + timedelta(days=3),
        ),
    )
    backdated = commit_declaration(
        ledger_db,
        _declare(
            subject_type,
            subject_key,
            to_state=scenario["backdated"],
            event_type=f"{subject_type}.{scenario['backdated']}",
            effective_at=T0 + timedelta(days=1),
        ),
    )
    # A fact learned late but true earlier: it committed (a current `recorded_at`, a past
    # `effective_at`) and joined history without displacing the later forward fact.
    assert backdated.recorded_at > second.recorded_at
    assert backdated.state is not None
    assert backdated.state.event_id == second.event_id

    reversal = commit_reversal(
        ledger_db,
        reverses_event_id=second.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-tests",
        reason="second_transition_declared_in_error",
    )
    assert reversal.state is not None
    # With `second` voided, the backdated fact — the latest surviving `effective_at` — wins.
    assert reversal.state.state == scenario["backdated"]
    assert reversal.state.event_id == backdated.event_id

    expected = _stored_current_state(ledger_db, subject_type, subject_key)
    assert expected is not None
    assert expected == (scenario["backdated"], T0 + timedelta(days=1), backdated.event_id)

    assert _independent_fold(ledger_db, subject_type, subject_key) == expected
    # And the voided `second` event stayed readable — a reversal is an append, not an edit.
    still_there = ledger_db.execute(
        "SELECT payload FROM ledger.events WHERE event_id = %s", (second.event_id,)
    ).fetchone()
    assert still_there == ({"to_state": scenario["second"]},)

    # The forward-declared event carries the flat-projection columns the STG_EVENTS contract needs.
    columns = ", ".join(FLAT_PROJECTION_COLUMNS)
    row = ledger_db.execute(
        f"SELECT {columns} FROM ledger.events WHERE event_id = %s",  # noqa: S608 - fixed column list, no interpolated input
        (forward.event_id,),
    ).fetchone()
    assert row is not None
    projected = dict(zip(FLAT_PROJECTION_COLUMNS, row, strict=True))
    assert projected["event_id"] == forward.event_id
    assert projected["subject_type"] == subject_type
    assert projected["subject_key"] == subject_key
    assert projected["effective_at"] == T0
    assert projected["recorded_at"] == forward.recorded_at
    assert projected["producer"] == "pulse-ledger-tests"
    assert projected["schema_version"] == 1
    assert projected["rule_version"] == CATALOG_VERSION
    assert (projected["actor_type"], projected["actor_id"]) == ("system", "fold-equivalence-tests")
    # `payload` is already parsed JSON (JSONB round-trips to a dict), not an opaque string.
    assert isinstance(projected["payload"], dict)
    assert projected["payload"] == {"to_state": scenario["entry"]}


@pytest.mark.parametrize("subject_type", sorted(SCENARIOS))
def test_independent_fold_equals_current_state_after_a_backfill(
    ledger_db: psycopg.Connection, subject_type: str
) -> None:
    scenario = SCENARIOS[subject_type]
    subject_key = "bf-1"

    gap = commit_declaration(
        ledger_db,
        _declare(
            subject_type,
            subject_key,
            to_state=None,
            event_type="reconstruction_gap",
            effective_at=T0,
            actor_id="backfill",
            producer="backfill",
            evidence_class="E4",
            epoch="reconstructed",
            evidence={"discarded": 1, "reason": "unsequenceable prefix"},
        ),
    )
    assert gap.state is None

    genesis = commit_declaration(
        ledger_db,
        _declare(
            subject_type,
            subject_key,
            to_state=scenario["backfill_anchor"],
            event_type=f"{subject_type}.backfill_genesis",
            effective_at=T0 + timedelta(minutes=1),
            actor_id="backfill",
            producer="backfill",
            evidence_class="E4",
            epoch="reconstructed",
        ),
        allow_arbitrary_genesis=True,
    )
    assert genesis.state is not None
    assert genesis.state.state == scenario["backfill_anchor"]

    expected = _stored_current_state(ledger_db, subject_type, subject_key)
    assert expected is not None
    assert expected == (scenario["backfill_anchor"], T0 + timedelta(minutes=1), genesis.event_id)

    # The independent fold steps over the non-state-bearing gap exactly as the commit path did.
    assert _independent_fold(ledger_db, subject_type, subject_key) == expected

    stored_gap = ledger_db.execute(
        "SELECT epoch, evidence_class, payload FROM ledger.events WHERE event_id = %s", (gap.event_id,)
    ).fetchone()
    assert stored_gap == ("reconstructed", "E4", {})
