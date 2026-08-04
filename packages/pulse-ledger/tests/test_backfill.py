"""Backfill mode (task 3.5) — the command-api spec's restricted-vocabulary requirement.

Three scenarios, split across the two layers that decide them:

1. **Forward writer rejected on backfill types** — decided at the HTTP boundary, where a
   declaration's event type and its authenticated writer are both in scope (`test_api_auth.py`'s
   pattern: a fake committer, no database).
2. **Gap + genesis sequence commits with reconstructed epoch** — the spec's "Genesis re-anchoring
   records the gap" scenario, against a real Postgres.
3. **A `resolution_hold` commits without changing the subject's current state** — the other
   non-state-bearing fact `commit_declaration` now accepts, also against a real Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_core.generated import CATALOG_VERSION
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration
from pulse_ledger.validation import IllegalTransitionError

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _rows(conn: psycopg.Connection, table: str) -> list[tuple[Any, ...]]:
    return conn.execute(f"SELECT * FROM ledger.{table}").fetchall()  # noqa: S608


# --- gap + genesis sequence, against a real Postgres -------------------------------------------


def test_reconstruction_gap_then_backfill_genesis_commit_with_the_reconstructed_epoch(
    ledger_db: psycopg.Connection,
) -> None:
    """The spec's "Genesis re-anchoring records the gap" scenario.

    A referral's reconstructed prefix does not parse as a legal path, so the backfill actor
    records the discarded evidence as a `reconstruction_gap` fact, then re-anchors the subject at
    the last confidently known state with `backfill_genesis`. Both commit; neither is a catalog
    entry point (`outreach` has an incoming edge), so only the backfill path's relaxed genesis
    check lets the second one through.
    """
    gap = commit_declaration(
        ledger_db,
        Declaration(
            subject_type="referral",
            subject_key="ref-1",
            event_type="reconstruction_gap",
            effective_at=T0,
            actor_type="system",
            actor_id="backfill",
            producer="backfill",
            evidence_class="E4",
            epoch="reconstructed",
            evidence={"discarded": 3, "reason": "unsequenceable prefix"},
        ),
    )
    assert gap.state is None
    assert _rows(ledger_db, "current_state") == []

    genesis = commit_declaration(
        ledger_db,
        Declaration(
            subject_type="referral",
            subject_key="ref-1",
            event_type="backfill_genesis",
            to_state="outreach",
            effective_at=T0 + timedelta(minutes=1),
            actor_type="system",
            actor_id="backfill",
            producer="backfill",
            evidence_class="E4",
            epoch="reconstructed",
        ),
        allow_arbitrary_genesis=True,
    )
    assert genesis.state is not None
    assert genesis.state.state == "outreach"
    assert genesis.rule_version == CATALOG_VERSION

    stored_gap = ledger_db.execute(
        "SELECT event_type, epoch, evidence_class, evidence, payload FROM ledger.events WHERE event_id = %s",
        (gap.event_id,),
    ).fetchone()
    assert stored_gap == (
        "reconstruction_gap",
        "reconstructed",
        "E4",
        {"discarded": 3, "reason": "unsequenceable prefix"},
        {},
    )

    stored_genesis = ledger_db.execute(
        "SELECT epoch, evidence_class FROM ledger.events WHERE event_id = %s", (genesis.event_id,)
    ).fetchone()
    assert stored_genesis == ("reconstructed", "E4")

    current_state = ledger_db.execute(
        "SELECT state, last_event_id FROM ledger.current_state WHERE subject_type = 'referral' AND subject_key = 'ref-1'"
    ).fetchone()
    assert current_state == ("outreach", genesis.event_id)


# --- resolution_hold: non-state-bearing, commits without moving current_state -------------------


def _received(conn: psycopg.Connection, subject_key: str = "ref-1") -> CommitResult:
    return commit_declaration(
        conn,
        Declaration(
            subject_type="referral",
            subject_key=subject_key,
            event_type="referral.received",
            to_state="received",
            effective_at=T0,
            actor_type="system",
            actor_id="intake",
            producer="pulse-ledger-tests",
        ),
    )


def test_a_resolution_hold_commits_without_changing_the_subjects_current_state(
    ledger_db: psycopg.Connection,
) -> None:
    received = _received(ledger_db)

    hold = commit_declaration(
        ledger_db,
        Declaration(
            subject_type="referral",
            subject_key="ref-1",
            event_type="resolution_hold",
            effective_at=T0 + timedelta(minutes=1),
            actor_type="system",
            actor_id="identity-resolver",
            producer="identity-resolver",
        ),
    )

    assert hold.state is not None
    assert hold.state.state == "received"
    assert hold.state.event_id == received.event_id

    stored = ledger_db.execute(
        "SELECT event_type, payload FROM ledger.events WHERE event_id = %s", (hold.event_id,)
    ).fetchone()
    assert stored == ("resolution_hold", {})

    current_state = ledger_db.execute(
        "SELECT state, last_event_id, updated_at FROM ledger.current_state"
        " WHERE subject_type = 'referral' AND subject_key = 'ref-1'"
    ).fetchone()
    assert current_state is not None
    state, last_event_id, _updated_at = current_state
    # The hold never reached current_state: it still names the genesis event, not the hold.
    assert (state, last_event_id) == ("received", received.event_id)


def test_a_resolution_hold_on_an_unknown_subject_type_is_refused(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(IllegalTransitionError):
        commit_declaration(
            ledger_db,
            Declaration(
                subject_type="patient",
                subject_key="p-1",
                event_type="resolution_hold",
                effective_at=T0,
                actor_type="system",
                actor_id="identity-resolver",
                producer="identity-resolver",
            ),
        )
    assert _rows(ledger_db, "events") == []


def test_a_resolution_hold_can_be_the_first_event_for_a_subject(ledger_db: psycopg.Connection) -> None:
    """A hold does not require a prior genesis; nothing requires current_state to exist yet."""
    hold = commit_declaration(
        ledger_db,
        Declaration(
            subject_type="referral",
            subject_key="ref-2",
            event_type="resolution_hold",
            effective_at=T0,
            actor_type="system",
            actor_id="identity-resolver",
            producer="identity-resolver",
        ),
    )
    assert hold.state is None
    assert _rows(ledger_db, "current_state") == []
    assert len(_rows(ledger_db, "events")) == 1
