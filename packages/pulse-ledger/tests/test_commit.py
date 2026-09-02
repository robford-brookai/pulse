"""The commit path — task 3.2's three obligations, against a real Postgres.

1. **Atomicity**: an injected failure after the event row leaves no partial write.
2. **Backdate fold order**: a fact learned late but true earlier commits, joins history, and does
   not become the current state.
3. **Reversal**: the correction references the event it voids, both stay readable, and the
   subject's state folds back.

Plus what the task's one-line objective names and the spec requires around them: `recorded_at` is
the server's and never a writer's, `effective_at` is canonical with `occurred_at` accepted as an
input alias, and the whole thing works as the service role — which cannot UPDATE or DELETE
`ledger.events`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from pulse_core.generated import CATALOG_VERSION
from pulse_ledger import commit as commit_module
from pulse_ledger.commit import (
    AlreadyReversedError,
    ConflictingEffectiveAtError,
    Declaration,
    MissingEffectiveAtError,
    NaiveTimestampError,
    ReversalLeavesNoStateError,
    ServerSetFieldError,
    UnknownEventError,
    commit_declaration,
    commit_reversal,
)
from pulse_ledger.validation import IllegalTransitionError

SERVICE_ROLE = "pulse_ledger_service"

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _declare(
    subject_type: str = "referral",
    subject_key: str = "ref-1",
    to_state: str = "received",
    effective_at: datetime | None = None,
    **overrides: Any,
) -> Declaration:
    fields: dict[str, Any] = {
        "subject_type": subject_type,
        "subject_key": subject_key,
        "event_type": f"{subject_type}.{to_state}",
        "to_state": to_state,
        "effective_at": effective_at or T0,
        "actor_type": "system",
        "actor_id": "verdict-relay",
        "producer": "pulse-ledger-tests",
    }
    fields.update(overrides)
    return Declaration(**fields)


def _rows(conn: psycopg.Connection, table: str) -> list[tuple[Any, ...]]:
    return conn.execute(f"SELECT * FROM ledger.{table}").fetchall()  # noqa: S608


def _current_state(conn: psycopg.Connection, subject_key: str = "ref-1") -> tuple[Any, ...] | None:
    return conn.execute(
        "SELECT state, effective_at, last_event_id, updated_at FROM ledger.current_state"
        " WHERE subject_type = %s AND subject_key = %s",
        ("referral", subject_key),
    ).fetchone()


# --- one transaction, three rows -------------------------------------------------------------


def test_a_legal_declaration_commits_event_state_and_outbox_together(ledger_db: psycopg.Connection) -> None:
    before = datetime.now(timezone.utc)
    result = commit_declaration(ledger_db, _declare())

    event = ledger_db.execute(
        "SELECT subject_type, subject_key, event_type, effective_at, recorded_at, rule_version, payload, epoch,"
        " evidence_class FROM ledger.events WHERE event_id = %s",
        (result.event_id,),
    ).fetchone()
    assert event is not None
    subject_type, subject_key, event_type, effective_at, recorded_at, rule_version, payload, epoch, evidence = event
    assert (subject_type, subject_key, event_type) == ("referral", "ref-1", "referral.received")
    assert effective_at == T0
    assert rule_version == CATALOG_VERSION
    assert payload == {"to_state": "received"}
    assert (epoch, evidence) == ("declared", "E0")

    # recorded_at is the server's clock, not the declared effective_at.
    assert recorded_at == result.recorded_at
    assert before <= recorded_at <= datetime.now(timezone.utc)
    assert recorded_at != effective_at

    assert _current_state(ledger_db) == ("received", T0, result.event_id, recorded_at)
    assert result.state is not None
    assert result.state.state == "received"

    outbox = ledger_db.execute(
        "SELECT subject_type, subject_key, seq, published_at FROM ledger.outbox WHERE event_id = %s",
        (result.event_id,),
    ).fetchone()
    assert outbox == ("referral", "ref-1", 1, None)
    assert result.outbox_seq == 1


def test_the_outbox_sequence_is_per_subject(ledger_db: psycopg.Connection) -> None:
    first = commit_declaration(ledger_db, _declare())
    second = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(hours=1)))
    other_subject = commit_declaration(ledger_db, _declare(subject_key="ref-2"))

    assert (first.outbox_seq, second.outbox_seq) == (1, 2)
    assert other_subject.outbox_seq == 1


def test_the_envelope_lineage_ids_are_stored_when_supplied(ledger_db: psycopg.Connection) -> None:
    correlation, causation = uuid.uuid4(), uuid.uuid4()
    result = commit_declaration(ledger_db, _declare(correlation_id=correlation, causation_id=causation))
    stored = ledger_db.execute(
        "SELECT correlation_id, causation_id FROM ledger.events WHERE event_id = %s", (result.event_id,)
    )
    assert stored.fetchone() == (correlation, causation)


def test_a_non_state_bearing_event_in_history_does_not_disturb_the_fold(ledger_db: psycopg.Connection) -> None:
    """`reconstruction_gap` (task 3.5) records evidence, not a state; the fold must step over it."""
    received = commit_declaration(ledger_db, _declare())
    ledger_db.execute(
        "INSERT INTO ledger.events"
        " (event_id, subject_type, subject_key, event_type, effective_at, producer, rule_version,"
        "  actor_type, actor_id, epoch, payload)"
        " VALUES (%s, 'referral', 'ref-1', 'referral.reconstruction_gap', %s, 'backfill', %s,"
        "         'system', 'backfill-loader', 'reconstructed', '{\"discarded\": 3}'::jsonb)",
        (uuid.uuid4(), T0 + timedelta(hours=1), CATALOG_VERSION),
    )

    result = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=1)))
    assert result.state is not None
    assert result.state.state == "resolved"
    # The gap event neither supplied the predecessor state nor blocked the legal transition.
    assert received.state is not None


def test_two_commits_inside_one_caller_transaction_get_distinct_recorded_at(
    ledger_db: psycopg.Connection,
) -> None:
    """The fold's tie-break needs a per-statement clock, not the transaction's frozen `now()`.

    Task 3.3 composes the idempotency-key insert into the same transaction as the commit, so this
    is the arrangement the write path actually runs in.
    """
    with ledger_db.transaction():
        first = commit_declaration(ledger_db, _declare())
        second = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(hours=1)))

    assert first.recorded_at < second.recorded_at
    # And the co-committed state is the later fact, which a collapsed tie-break could not guarantee.
    assert _current_state(ledger_db) == ("resolved", T0 + timedelta(hours=1), second.event_id, second.recorded_at)


def test_a_caller_transaction_that_aborts_takes_the_whole_commit_with_it(ledger_db: psycopg.Connection) -> None:
    injected = RuntimeError("caller changed its mind")
    with pytest.raises(RuntimeError), ledger_db.transaction():
        commit_declaration(ledger_db, _declare())
        raise injected

    assert _rows(ledger_db, "events") == []
    assert _rows(ledger_db, "current_state") == []
    assert _rows(ledger_db, "outbox") == []


def test_the_phi_bearing_fields_stay_out_of_the_declarations_repr() -> None:
    """`payload` and `evidence` are the schema-free fields; a traceback must not render them."""
    rendered = repr(
        _declare(
            payload={"note": "synthetic-note-do-not-log"},
            evidence={"source": "synthetic-do-not-log"},
        )
    )
    assert "do-not-log" not in rendered
    # The fields that are safe to see in an error are still there.
    assert "ref-1" in rendered
    assert "referral" in rendered


def test_the_commit_path_runs_as_the_service_role(ledger_db: psycopg.Connection) -> None:
    """The role that cannot UPDATE or DELETE events still has everything the commit path needs."""
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    first = commit_declaration(ledger_db, _declare())
    second = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(hours=1)))

    assert second.state is not None
    assert second.state.state == "resolved"
    assert first.event_id != second.event_id


# --- atomicity -------------------------------------------------------------------------------


def test_an_injected_failure_after_the_event_leaves_no_partial_write(
    ledger_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    injected = RuntimeError("outbox write failed")

    def _boom(*_args: object, **_kwargs: object) -> int:
        raise injected

    monkeypatch.setattr(commit_module, "_insert_outbox_row", _boom)
    with pytest.raises(RuntimeError) as raised:
        commit_declaration(ledger_db, _declare())
    assert raised.value is injected

    assert _rows(ledger_db, "events") == []
    assert _rows(ledger_db, "current_state") == []
    assert _rows(ledger_db, "outbox") == []


def test_an_illegal_transition_is_rejected_before_anything_is_written(ledger_db: psycopg.Connection) -> None:
    commit_declaration(ledger_db, _declare(subject_type="billing_episode", subject_key="be-1", to_state="open"))
    commit_declaration(
        ledger_db,
        _declare(
            subject_type="billing_episode",
            subject_key="be-1",
            to_state="qualified",
            effective_at=T0 + timedelta(days=1),
        ),
    )
    commit_declaration(
        ledger_db,
        _declare(
            subject_type="billing_episode",
            subject_key="be-1",
            to_state="reported",
            effective_at=T0 + timedelta(days=2),
        ),
    )
    events_before = len(_rows(ledger_db, "events"))

    with pytest.raises(IllegalTransitionError) as raised:
        commit_declaration(
            ledger_db,
            _declare(
                subject_type="billing_episode",
                subject_key="be-1",
                to_state="qualified",
                effective_at=T0 + timedelta(days=3),
            ),
        )
    assert raised.value.from_state == "reported"
    assert raised.value.catalog_version == CATALOG_VERSION
    assert "reported" in raised.value.reason

    assert len(_rows(ledger_db, "events")) == events_before
    state = ledger_db.execute(
        "SELECT state FROM ledger.current_state WHERE subject_type = 'billing_episode' AND subject_key = 'be-1'"
    ).fetchone()
    assert state == ("reported",)


def test_a_subject_cannot_enter_the_ledger_part_way_through_its_state_machine(
    ledger_db: psycopg.Connection,
) -> None:
    with pytest.raises(IllegalTransitionError) as raised:
        commit_declaration(ledger_db, _declare(to_state="outreach"))
    assert raised.value.from_state is None
    assert "entry state" in raised.value.reason
    assert _rows(ledger_db, "events") == []

    # The restricted backfill path is what may re-anchor a subject mid-machine (task 3.5).
    result = commit_declaration(
        ledger_db,
        _declare(to_state="outreach", epoch="reconstructed", evidence_class="E4"),
        allow_arbitrary_genesis=True,
    )
    assert result.state is not None
    assert result.state.state == "outreach"
    assert result.rule_version == CATALOG_VERSION


def test_arbitrary_genesis_still_refuses_a_state_the_catalog_does_not_contain(
    ledger_db: psycopg.Connection,
) -> None:
    """The relaxation is of the entry-state rule, not of catalog membership.

    `current_state.state` is plain text with no check constraint, so a typo that got through here
    would sit in the store stamped with a `rule_version` claiming catalog conformance.
    """
    with pytest.raises(IllegalTransitionError) as raised:
        commit_declaration(ledger_db, _declare(to_state="recieved"), allow_arbitrary_genesis=True)
    assert "recieved" in raised.value.reason
    assert _rows(ledger_db, "events") == []

    with pytest.raises(IllegalTransitionError):
        commit_declaration(
            ledger_db, _declare(subject_type="spaceship", to_state="docked"), allow_arbitrary_genesis=True
        )
    assert _rows(ledger_db, "events") == []


def test_a_catalog_legal_communication_consent_transition_commits(ledger_db: psycopg.Connection) -> None:
    """The gap once pinned here (see `0005_admit_communication_consent_subject.py`), closed for
    `communication_consent`: the catalog seed carries the subject (`ownership: recorded`) and the
    subject-type checks admit it as of migration 0005, so validation and commit agree — event,
    `current_state` fold, and outbox row land in one transaction, exactly as `record_communication_
    consent` (consent-ingress, the consent sweep) needs.
    """
    minted = commit_declaration(
        ledger_db,
        _declare(subject_type="communication_consent", subject_key="cc-1", to_state="unset"),
    )
    opted_in = commit_declaration(
        ledger_db,
        _declare(
            subject_type="communication_consent",
            subject_key="cc-1",
            to_state="opted_in",
            effective_at=T0 + timedelta(days=1),
        ),
    )

    assert minted.rule_version == CATALOG_VERSION
    assert opted_in.state is not None
    assert opted_in.state.state == "opted_in"
    state = ledger_db.execute(
        "SELECT state, last_event_id FROM ledger.current_state"
        " WHERE subject_type = 'communication_consent' AND subject_key = 'cc-1'"
    ).fetchone()
    assert state == ("opted_in", opted_in.event_id)


def test_a_catalog_legal_coverage_transition_commits(ledger_db: psycopg.Connection) -> None:
    """The gap the test above pins, closed for `coverage` by migration 0004: catalog 1.1.0 added
    the subject and the same change widens the store, so validation and commit agree — event,
    `current_state` fold, and outbox row land in one transaction.
    """
    minted = commit_declaration(
        ledger_db, _declare(subject_type="coverage", subject_key="cov-1", to_state="unverified")
    )
    verified = commit_declaration(
        ledger_db,
        _declare(
            subject_type="coverage",
            subject_key="cov-1",
            to_state="verified_active",
            effective_at=T0 + timedelta(days=1),
        ),
    )

    assert minted.rule_version == CATALOG_VERSION
    assert verified.state is not None
    assert verified.state.state == "verified_active"
    state = ledger_db.execute(
        "SELECT state, last_event_id FROM ledger.current_state"
        " WHERE subject_type = 'coverage' AND subject_key = 'cov-1'"
    ).fetchone()
    assert state == ("verified_active", verified.event_id)
    outbox = ledger_db.execute(
        "SELECT subject_type, subject_key, seq FROM ledger.outbox WHERE event_id = %s",
        (verified.event_id,),
    ).fetchone()
    assert outbox == ("coverage", "cov-1", 2)


# --- bitemporality: backdating and fold order -------------------------------------------------


def test_a_backdated_declaration_joins_history_without_becoming_the_current_state(
    ledger_db: psycopg.Connection,
) -> None:
    """`open` at T0, `qualified` at T2, then `not_qualified` learned last but true at T1.

    BillingEpisode is the case that stays coherent under a mid-history insert: the backdated event
    is legal from `open`, and the T2 event that follows it is legal from `not_qualified` — the
    `qualified ⇄ not_qualified` re-entry the catalog carries.
    """
    subject = {"subject_type": "billing_episode", "subject_key": "be-1"}
    opened = commit_declaration(ledger_db, _declare(**subject, to_state="open"))
    qualified = commit_declaration(
        ledger_db, _declare(**subject, to_state="qualified", effective_at=T0 + timedelta(days=2))
    )
    backdated = commit_declaration(
        ledger_db, _declare(**subject, to_state="not_qualified", effective_at=T0 + timedelta(days=1))
    )

    # It committed, with a past effective_at and a current recorded_at.
    assert backdated.recorded_at > qualified.recorded_at
    assert backdated.state is not None

    # And the fold ordered by effective_at, so the current state is still the T2 fact.
    assert backdated.state.state == "qualified"
    assert backdated.state.event_id == qualified.event_id
    state = ledger_db.execute(
        "SELECT state, effective_at, last_event_id FROM ledger.current_state"
        " WHERE subject_type = 'billing_episode' AND subject_key = 'be-1'"
    ).fetchone()
    assert state == ("qualified", T0 + timedelta(days=2), qualified.event_id)

    # All three events are in history, and the outbox saw the backdated one last.
    assert len(_rows(ledger_db, "events")) == 3
    assert (opened.outbox_seq, qualified.outbox_seq, backdated.outbox_seq) == (1, 2, 3)


def test_a_backdated_declaration_is_validated_against_the_state_that_held_then(
    ledger_db: psycopg.Connection,
) -> None:
    commit_declaration(ledger_db, _declare())
    commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=3)))

    # At T0+1 day the referral was `received`, from which `closed` is legal even though the
    # subject's latest state is `resolved`.
    result = commit_declaration(ledger_db, _declare(to_state="closed", effective_at=T0 + timedelta(days=1)))
    assert result.state is not None
    assert result.state.state == "resolved"

    # And a declaration at T0+2 days departs from that just-backdated `closed`, not from the
    # subject's latest `resolved` — so `screened` is illegal, because `closed` is terminal.
    with pytest.raises(IllegalTransitionError) as raised:
        commit_declaration(ledger_db, _declare(to_state="screened", effective_at=T0 + timedelta(days=2)))
    assert raised.value.from_state == "closed"


def test_a_writer_cannot_supply_recorded_at() -> None:
    with pytest.raises(ServerSetFieldError) as raised:
        Declaration.from_mapping({
            "subject_type": "referral",
            "subject_key": "ref-1",
            "event_type": "referral.received",
            "to_state": "received",
            "effective_at": T0,
            "recorded_at": T0,
            "actor_type": "system",
            "actor_id": "verdict-relay",
            "producer": "tests",
        })
    assert raised.value.name == "recorded_at"


def test_occurred_at_is_accepted_as_an_input_alias_and_normalised(ledger_db: psycopg.Connection) -> None:
    declaration = Declaration.from_mapping({
        "subject_type": "referral",
        "subject_key": "ref-1",
        "event_type": "referral.received",
        "to_state": "received",
        "occurred_at": T0,
        "actor_type": "system",
        "actor_id": "verdict-relay",
        "producer": "tests",
    })
    assert declaration.effective_at == T0

    result = commit_declaration(ledger_db, declaration)
    stored = ledger_db.execute("SELECT effective_at FROM ledger.events WHERE event_id = %s", (result.event_id,))
    assert stored.fetchone() == (T0,)


def test_the_alias_and_the_canonical_name_may_not_disagree() -> None:
    body = {
        "subject_type": "referral",
        "subject_key": "ref-1",
        "event_type": "referral.received",
        "to_state": "received",
        "actor_type": "system",
        "actor_id": "verdict-relay",
        "producer": "tests",
    }
    with pytest.raises(ConflictingEffectiveAtError):
        Declaration.from_mapping({**body, "effective_at": T0, "occurred_at": T0 + timedelta(days=1)})
    # Identical values are the same fact stated twice, which is fine.
    assert Declaration.from_mapping({**body, "effective_at": T0, "occurred_at": T0}).effective_at == T0
    with pytest.raises(MissingEffectiveAtError):
        Declaration.from_mapping(body)


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(NaiveTimestampError) as raised:
        _declare(effective_at=datetime(2026, 7, 1, 12, 0))
    assert raised.value.name == "effective_at"
    with pytest.raises(NaiveTimestampError):
        _declare(
            evidence_class="E3",
            epoch="reconstructed",
            evidence_bounds=(datetime(2026, 1, 1), T0),
        )


def test_interpolated_backfill_carries_its_bounds(ledger_db: psycopg.Connection) -> None:
    lower, upper = T0 - timedelta(days=30), T0
    result = commit_declaration(
        ledger_db,
        _declare(
            evidence_class="E3",
            epoch="reconstructed",
            evidence_bounds=(lower, upper),
            evidence={"source": "synthetic-fixture"},
        ),
    )
    stored = ledger_db.execute(
        "SELECT evidence_class, epoch, evidence_bound_lower, evidence_bound_upper, evidence"
        " FROM ledger.events WHERE event_id = %s",
        (result.event_id,),
    ).fetchone()
    assert stored == ("E3", "reconstructed", lower, upper, {"source": "synthetic-fixture"})


# --- correction by reversal -------------------------------------------------------------------


def test_a_reversal_references_the_voided_event_preserves_history_and_folds_state_back(
    ledger_db: psycopg.Connection,
) -> None:
    received = commit_declaration(ledger_db, _declare())
    mistake = commit_declaration(ledger_db, _declare(to_state="closed", effective_at=T0 + timedelta(days=1)))
    assert _current_state(ledger_db) is not None

    reversal = commit_reversal(
        ledger_db,
        reverses_event_id=mistake.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-tests",
        reason="closed_in_error",
    )

    # The reversal references what it voids, and sorts alongside it.
    stored = ledger_db.execute(
        "SELECT event_type, reverses_event_id, effective_at, payload, evidence_class, epoch, recorded_at"
        " FROM ledger.events WHERE event_id = %s",
        (reversal.event_id,),
    ).fetchone()
    assert stored is not None
    event_type, reverses, effective_at, payload, evidence_class, epoch, recorded_at = stored
    assert event_type == "referral.closed.reversed"
    assert reverses == mistake.event_id
    assert effective_at == T0 + timedelta(days=1)
    # The withdrawn fact is reachable by the reference, not copied into a second row.
    assert payload == {"reason": "closed_in_error"}
    # The correction is its own declared act, and its recorded_at is the server's.
    assert (evidence_class, epoch) == ("E0", "declared")
    assert recorded_at > mistake.recorded_at

    # Both the voided event and the reversal remain readable — nothing was edited away.
    assert len(_rows(ledger_db, "events")) == 3
    voided = ledger_db.execute("SELECT payload FROM ledger.events WHERE event_id = %s", (mistake.event_id,)).fetchone()
    assert voided == ({"to_state": "closed"},)

    # And the subject folded back to the state before the mistake.
    assert reversal.state is not None
    assert reversal.state.state == "received"
    assert _current_state(ledger_db) == ("received", T0, received.event_id, received.recorded_at)

    # The reversal is relayed like any other event.
    assert reversal.outbox_seq == 3


def test_a_reversal_of_an_unknown_event_is_refused(ledger_db: psycopg.Connection) -> None:
    missing = uuid.uuid4()
    with pytest.raises(UnknownEventError) as raised:
        commit_reversal(
            ledger_db,
            reverses_event_id=missing,
            actor_type="human",
            actor_id="ops-analyst",
            producer="pulse-ledger-tests",
            reason="typo",
        )
    assert raised.value.event_id == missing
    assert _rows(ledger_db, "events") == []


def test_an_event_cannot_be_reversed_twice(ledger_db: psycopg.Connection) -> None:
    commit_declaration(ledger_db, _declare())
    mistake = commit_declaration(ledger_db, _declare(to_state="closed", effective_at=T0 + timedelta(days=1)))
    first = commit_reversal(
        ledger_db,
        reverses_event_id=mistake.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-tests",
        reason="closed_in_error",
    )
    with pytest.raises(AlreadyReversedError) as raised:
        commit_reversal(
            ledger_db,
            reverses_event_id=mistake.event_id,
            actor_type="human",
            actor_id="ops-analyst",
            producer="pulse-ledger-tests",
            reason="closed_in_error",
        )
    assert raised.value.reversal_id == first.event_id
    assert len(_rows(ledger_db, "events")) == 3


def test_reversing_a_subjects_only_fact_is_refused_and_writes_nothing(ledger_db: psycopg.Connection) -> None:
    genesis = commit_declaration(ledger_db, _declare())
    with pytest.raises(ReversalLeavesNoStateError):
        commit_reversal(
            ledger_db,
            reverses_event_id=genesis.event_id,
            actor_type="human",
            actor_id="ops-analyst",
            producer="pulse-ledger-tests",
            reason="never_happened",
        )
    assert len(_rows(ledger_db, "events")) == 1
    assert _current_state(ledger_db) == ("received", T0, genesis.event_id, genesis.recorded_at)


def test_a_declaration_after_a_reversal_departs_from_the_refolded_state(ledger_db: psycopg.Connection) -> None:
    commit_declaration(ledger_db, _declare())
    mistake = commit_declaration(ledger_db, _declare(to_state="closed", effective_at=T0 + timedelta(days=1)))
    commit_reversal(
        ledger_db,
        reverses_event_id=mistake.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-tests",
        reason="closed_in_error",
    )
    # `received -> resolved` is legal; it would not have been from the voided `closed`.
    result = commit_declaration(ledger_db, _declare(to_state="resolved", effective_at=T0 + timedelta(days=2)))
    assert result.state is not None
    assert result.state.state == "resolved"
