"""Coverage first-declare and enumeration (task 2.3, billing-state), against a real Postgres.

`coverage` is the one catalog subject with no registration command: there is no
`open_coverage` the way there is `open_billing_episode`. The first verdict for a patient x payer
key must still mint the subject at its derived initial state (`unverified`, no incoming edge)
and apply the paired transition in the same run — no separate registration step
(`pulse_ledger.validation.validate_first_transition`, `IMPLICIT_MINT_SUBJECT_TYPES`).

This suite pins that mechanism plus the two other coverage-state requirements this task owns:
enumeration from `current_state` (never a projection), and that a transition's `to_state` stays
catalog-coarse while verdict detail (QMB status and friends) stays in the declaration's payload,
never in the state vocabulary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_ledger.commit import Declaration, commit_declaration
from pulse_ledger.reads import enumerate_state
from pulse_ledger.validation import IllegalTransitionError

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _declare_coverage(
    subject_key: str,
    to_state: str,
    effective_at: datetime,
    **overrides: Any,
) -> Declaration:
    fields: dict[str, Any] = {
        "subject_type": "coverage",
        "subject_key": subject_key,
        "event_type": "declare_transition",
        "to_state": to_state,
        "effective_at": effective_at,
        "actor_type": "system",
        "actor_id": "verdict-relay",
        "producer": "pulse-ledger-tests",
    }
    fields.update(overrides)
    return Declaration(**fields)


def _cover(conn: psycopg.Connection, subject_key: str, *to_states: str) -> list[Any]:
    """Walk one coverage subject through `to_states`, one declaration per step.

    The first declaration is the "verdict" — an unseen key, straight to whatever the paired
    transition names — exactly what the relay submits; every step after departs from the
    subject's now-existing current state.
    """
    return [
        commit_declaration(conn, _declare_coverage(subject_key, state, T0 + timedelta(days=step)))
        for step, state in enumerate(to_states)
    ]


def _current_state(conn: psycopg.Connection, subject_key: str) -> str | None:
    row = conn.execute(
        "SELECT state FROM ledger.current_state WHERE subject_type = 'coverage' AND subject_key = %s",
        (subject_key,),
    ).fetchone()
    return None if row is None else row[0]


def _event_count(conn: psycopg.Connection, subject_key: str) -> int:
    row = conn.execute(
        "SELECT count(*) FROM ledger.events WHERE subject_type = 'coverage' AND subject_key = %s",
        (subject_key,),
    ).fetchone()
    assert row is not None
    return row[0]


# --- Scenario: First declare mints and transitions --------------------------------------------


class TestFirstDeclareMintsAndTransitions:
    def test_a_positive_first_verdict_mints_and_transitions_to_verified_active(
        self, ledger_db: psycopg.Connection
    ) -> None:
        result = commit_declaration(ledger_db, _declare_coverage("cov-mint-1", "verified_active", T0))

        assert result.state is not None
        assert result.state.state == "verified_active"
        assert _current_state(ledger_db, "cov-mint-1") == "verified_active"
        # No separate registration event was written for the implicit `unverified` predecessor —
        # the mint and the transition are the one declared event.
        assert _event_count(ledger_db, "cov-mint-1") == 1

    def test_a_negative_first_verdict_mints_and_transitions_to_verified_inactive(
        self, ledger_db: psycopg.Connection
    ) -> None:
        commit_declaration(ledger_db, _declare_coverage("cov-mint-2", "verified_inactive", T0))

        assert _current_state(ledger_db, "cov-mint-2") == "verified_inactive"
        assert _event_count(ledger_db, "cov-mint-2") == 1

    def test_a_second_verdict_for_the_same_key_transitions_without_re_minting(
        self, ledger_db: psycopg.Connection
    ) -> None:
        _cover(ledger_db, "cov-mint-3", "verified_active")

        second = commit_declaration(
            ledger_db, _declare_coverage("cov-mint-3", "verified_inactive", T0 + timedelta(days=1))
        )

        assert second.state is not None
        assert second.state.state == "verified_inactive"
        assert _current_state(ledger_db, "cov-mint-3") == "verified_inactive"
        # Two declared events total: the minting verdict and the second verdict's transition —
        # never a third event for a re-mint.
        assert _event_count(ledger_db, "cov-mint-3") == 2

    def test_an_explicit_genesis_at_unverified_still_works_unaffected(self, ledger_db: psycopg.Connection) -> None:
        """The ordinary genesis path (to_state == the entry state itself) is untouched."""
        commit_declaration(ledger_db, _declare_coverage("cov-explicit-1", "unverified", T0))

        assert _current_state(ledger_db, "cov-explicit-1") == "unverified"

    def test_a_first_verdict_landing_on_a_state_unreachable_from_unverified_is_still_rejected(
        self, ledger_db: psycopg.Connection
    ) -> None:
        """Implicit mint is not a blanket relaxation: `terminated` isn't adjacent to `unverified`."""
        with pytest.raises(IllegalTransitionError) as raised:
            commit_declaration(ledger_db, _declare_coverage("cov-mint-bad", "terminated", T0))

        assert raised.value.subject_type == "coverage"
        assert raised.value.to_state == "terminated"

    def test_other_subject_types_still_require_their_explicit_genesis_state(
        self, ledger_db: psycopg.Connection
    ) -> None:
        """The implicit-mint carve-out is coverage-only; every other subject keeps its rule."""
        declaration = Declaration(
            subject_type="enrollment",
            subject_key="enr-no-mint",
            event_type="enrollment.active",
            to_state="active",  # not enrollment's entry state ("pending_start")
            effective_at=T0,
            actor_type="system",
            actor_id="verdict-relay",
            producer="pulse-ledger-tests",
        )
        with pytest.raises(IllegalTransitionError) as raised:
            commit_declaration(ledger_db, declaration)

        assert raised.value.subject_type == "enrollment"
        assert raised.value.from_state is None


# --- Scenario: A verified coverage carries its detail in evidence, not state ------------------


class TestDetailStaysInEvidenceNotState:
    def test_qmb_detail_in_the_payload_never_reaches_the_committed_state(self, ledger_db: psycopg.Connection) -> None:
        declaration = _declare_coverage(
            "cov-detail-1",
            "verified_active",
            T0,
            payload={"qmb_status": "qualified", "benefit_category": "dual_eligible"},
            evidence={"lineage_ref": "dbt-run-2026-08-01T02"},
        )

        result = commit_declaration(ledger_db, declaration)

        assert result.state is not None
        assert result.state.state == "verified_active"  # coarse vocabulary only
        assert "qmb" not in result.state.state

        stored_payload = ledger_db.execute(
            "SELECT payload FROM ledger.events WHERE event_id = %s", (result.event_id,)
        ).fetchone()[0]
        assert stored_payload["qmb_status"] == "qualified"  # detail lives in the event, not the state

        current_state_columns = {
            desc.name
            for desc in ledger_db.execute(
                "SELECT * FROM ledger.current_state WHERE subject_type = 'coverage' LIMIT 0"
            ).description
        }
        assert "qmb_status" not in current_state_columns
        assert "payload" not in current_state_columns


# --- Scenario: Lapsed coverage enumerates from the ledger --------------------------------------


class TestEnumerationFromCurrentState:
    def test_lapsed_coverage_enumerates_exactly_the_lapsed_subjects(self, ledger_db: psycopg.Connection) -> None:
        _cover(ledger_db, "cov-active", "verified_active")
        _cover(ledger_db, "cov-lapsed-1", "verified_active", "lapsed")
        _cover(ledger_db, "cov-lapsed-2", "verified_inactive", "lapsed")
        _cover(ledger_db, "cov-terminated", "verified_active", "terminated")

        lapsed = enumerate_state(ledger_db, "coverage", ["lapsed"])

        assert [row.subject_key for row in lapsed] == ["cov-lapsed-1", "cov-lapsed-2"]
        assert all(row.state == "lapsed" for row in lapsed)
        assert all(row.subject_type == "coverage" for row in lapsed)

    def test_enumeration_reflects_the_co_committed_row_not_a_projection(self, ledger_db: psycopg.Connection) -> None:
        events = _cover(ledger_db, "cov-fresh", "verified_active", "lapsed")
        (row,) = enumerate_state(ledger_db, "coverage", ["lapsed"])

        assert row.last_event_id == events[-1].event_id
        assert row.effective_at == T0 + timedelta(days=1)
