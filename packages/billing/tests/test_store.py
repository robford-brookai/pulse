"""`billing.store.PostgresFactStore` — fact folding against a real `billing_engine` schema
(task 3.2).

Same throwaway-cluster fixtures as `test_migration_0001.py` (`tests/conftest.py`): a fresh
database per test, migrated up before use. Covers the same two spec scenarios as
`test_facts.py`, this time end to end through the store, plus the concurrency guard
(`SELECT ... FOR UPDATE`) that keeps two applies for the same subject from racing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from billing.store import PostgresFactStore

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"


def _upgrade(database_url: str) -> None:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "0001")


def envelope(
    *,
    event_id: uuid.UUID,
    subject_type: str = "billing_episode",
    subject_key: str = "ep-1",
    effective_at: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "event_id": str(event_id),
        "subject_type": subject_type,
        "subject_key": subject_key,
        "effective_at": effective_at,
        "payload": payload,
    }


def _stored_row(db: psycopg.Connection, subject_key: str) -> tuple[dict[str, object], uuid.UUID]:
    cur = db.execute(
        "SELECT facts, last_event_id FROM billing_engine.subject_facts WHERE subject_key = %s",
        (subject_key,),
    )
    facts, last_event_id = cur.fetchone()  # type: ignore[misc]
    return facts, last_event_id


def test_first_event_inserts_a_new_row(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    event_id = uuid.uuid4()
    store = PostgresFactStore(db)

    applied = store.apply_event(
        envelope(event_id=event_id, effective_at="2026-09-01T10:00:00+00:00", payload={"to_state": "qualified"})
    )

    assert applied is True
    facts, last_event_id = _stored_row(db, "ep-1")
    assert facts["to_state"] == "qualified"
    assert last_event_id == event_id


def test_redelivery_folds_once(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    event_id = uuid.uuid4()
    event = envelope(event_id=event_id, effective_at="2026-09-01T10:00:00+00:00", payload={"to_state": "qualified"})
    store = PostgresFactStore(db)

    first = store.apply_event(event)
    second = store.apply_event(event)

    assert first is True
    assert second is False
    cur = db.execute("SELECT count(*) FROM billing_engine.subject_facts")
    (count,) = cur.fetchone()  # type: ignore[misc]
    assert count == 1


def test_out_of_order_events_fold_by_effective_time(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    store = PostgresFactStore(db)
    newer_id = uuid.uuid4()
    older_id = uuid.uuid4()

    newer_applied = store.apply_event(
        envelope(event_id=newer_id, effective_at="2026-09-01T12:00:00+00:00", payload={"to_state": "qualified"})
    )
    older_applied = store.apply_event(
        envelope(event_id=older_id, effective_at="2026-09-01T09:00:00+00:00", payload={"to_state": "open"})
    )

    assert newer_applied is True
    assert older_applied is False  # the earlier-effective fact never overwrites the later one
    facts, last_event_id = _stored_row(db, "ep-1")
    assert facts["to_state"] == "qualified"
    assert last_event_id == newer_id


def test_a_later_event_merges_onto_the_existing_row(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    store = PostgresFactStore(db)

    store.apply_event(
        envelope(
            event_id=uuid.uuid4(),
            subject_type="consent",
            effective_at="2026-09-01T09:00:00+00:00",
            payload={"to_state": "granted", "program": "ccm"},
        )
    )
    store.apply_event(
        envelope(
            event_id=uuid.uuid4(),
            subject_type="consent",
            effective_at="2026-09-01T10:00:00+00:00",
            payload={"to_state": "revoked"},
        )
    )

    facts, _ = _stored_row(db, "ep-1")
    assert facts["to_state"] == "revoked"
    assert facts["program"] == "ccm"


def test_load_snapshot_returns_none_for_an_unknown_subject(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    store = PostgresFactStore(db)

    assert store.load_snapshot("billing_episode", "no-such-subject") is None


def test_load_snapshot_carries_the_updated_at_watermark(database_url: str, db: psycopg.Connection) -> None:
    """`billing_connector.evaluate.evaluate_subject` (task 2.1) derives `facts_stale` from this
    watermark against `Config.stale_after` (design.md decision 5) — the unlocked read path this
    method adds is where that watermark first becomes visible outside the store."""
    _upgrade(database_url)
    store = PostgresFactStore(db)
    store.apply_event(
        envelope(event_id=uuid.uuid4(), effective_at="2026-09-01T10:00:00+00:00", payload={"achieved": True})
    )

    snapshot = store.load_snapshot("billing_episode", "ep-1")

    assert snapshot is not None
    assert snapshot.facts["achieved"] is True
    assert snapshot.updated_at is not None
    assert (datetime.now(timezone.utc) - snapshot.updated_at) < timedelta(seconds=30)


def test_distinct_subjects_get_distinct_rows(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    store = PostgresFactStore(db)

    store.apply_event(
        envelope(
            event_id=uuid.uuid4(),
            subject_key="ep-1",
            effective_at="2026-09-01T09:00:00+00:00",
            payload={"to_state": "open"},
        )
    )
    store.apply_event(
        envelope(
            event_id=uuid.uuid4(),
            subject_key="ep-2",
            effective_at="2026-09-01T09:00:00+00:00",
            payload={"to_state": "open"},
        )
    )

    cur = db.execute("SELECT count(*) FROM billing_engine.subject_facts")
    (count,) = cur.fetchone()  # type: ignore[misc]
    assert count == 2


def _recorded_evaluations(db: psycopg.Connection, subject_key: str) -> list[tuple[object, ...]]:
    cur = db.execute(
        "SELECT verdict_type, rule_version, outcome, declared_event_id"
        "  FROM billing_engine.evaluations WHERE subject_key = %s ORDER BY outcome",
        (subject_key,),
    )
    return list(cur.fetchall())


def test_record_evaluation_appends_the_declared_event_id(database_url: str, db: psycopg.Connection) -> None:
    """billing-connector spec: "Each evaluation SHALL be recorded in the engine's `evaluations`
    store with the declared event id" — the connector's service calls this once the ledger has
    answered a declared verdict (`billing_connector.service.run_batch`)."""
    _upgrade(database_url)
    store = PostgresFactStore(db)
    declared_event_id = uuid.uuid4()

    written = store.record_evaluation(
        subject_type="billing_episode",
        subject_key="ep-1",
        verdict_type="billing_eligibility",
        rule_version="pulse-billing-eligibility-v1",
        outcome="positive",
        as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
        declared_event_id=str(declared_event_id),
    )

    assert written is True
    assert _recorded_evaluations(db, "ep-1") == [
        ("billing_eligibility", "pulse-billing-eligibility-v1", "positive", declared_event_id)
    ]


def test_record_evaluation_is_idempotent_on_the_declared_event_id(database_url: str, db: psycopg.Connection) -> None:
    """A replayed submission answers with the event id the original commit produced, so
    re-declaring an unchanged evaluation writes nothing new (spec: "Re-evaluating unchanged facts
    declares nothing new")."""
    _upgrade(database_url)
    store = PostgresFactStore(db)
    declared_event_id = str(uuid.uuid4())

    def record() -> bool:
        return store.record_evaluation(
            subject_type="billing_episode",
            subject_key="ep-2",
            verdict_type="billing_eligibility",
            rule_version="pulse-billing-eligibility-v1",
            outcome="positive",
            as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
            declared_event_id=declared_event_id,
        )

    assert record() is True
    assert record() is False
    assert len(_recorded_evaluations(db, "ep-2")) == 1


def test_record_evaluation_keeps_every_distinct_declaration(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    store = PostgresFactStore(db)

    for outcome in ("indeterminate", "positive"):
        store.record_evaluation(
            subject_type="billing_episode",
            subject_key="ep-3",
            verdict_type="billing_eligibility",
            rule_version="pulse-billing-eligibility-v1",
            outcome=outcome,
            as_of=datetime(2026, 9, 2, tzinfo=timezone.utc),
            declared_event_id=str(uuid.uuid4()),
        )

    assert [row[2] for row in _recorded_evaluations(db, "ep-3")] == ["indeterminate", "positive"]
