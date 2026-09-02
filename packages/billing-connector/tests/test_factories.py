"""Fixture builders produce valid snapshots per the engine's fact schema (task 1.4).

`make_facts`/`make_stale_facts`/`make_event` are the corpus's only source of test data; this
suite pins that what they build is accepted by the real `billing.facts` fold, not an invented
shape a later evaluate/declare test would silently rely on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from billing.facts import SubjectFactsSnapshot, fold_event

from tests.factories import make_event, make_facts, make_stale_facts


class TestMakeFacts:
    def test_builds_a_real_subject_facts_snapshot(self) -> None:
        snapshot = make_facts(facts={"achieved": True})
        assert isinstance(snapshot, SubjectFactsSnapshot)
        assert snapshot.facts["achieved"] is True
        assert snapshot.folded_as_of is not None

    def test_defaults_to_a_fresh_watermark(self) -> None:
        snapshot = make_facts()
        assert snapshot.folded_as_of is not None
        as_of = datetime.fromisoformat(snapshot.folded_as_of)
        assert (datetime.now(timezone.utc) - as_of) < timedelta(seconds=5)

    def test_updated_at_also_defaults_to_a_fresh_watermark(self) -> None:
        """`updated_at` is the store watermark `evaluate_subject` derives `facts_stale` from
        (spec: "Staleness comes from the connector's own watermark") — distinct from
        `folded_as_of`'s business time."""
        snapshot = make_facts()
        assert snapshot.updated_at is not None
        assert (datetime.now(timezone.utc) - snapshot.updated_at) < timedelta(seconds=5)


class TestMakeStaleFacts:
    def test_the_watermark_is_older_than_the_requested_margin(self) -> None:
        snapshot = make_stale_facts(stale_by=timedelta(days=1))
        assert snapshot.folded_as_of is not None
        as_of = datetime.fromisoformat(snapshot.folded_as_of)
        assert (datetime.now(timezone.utc) - as_of) >= timedelta(days=1)

    def test_updated_at_is_also_older_than_the_requested_margin(self) -> None:
        snapshot = make_stale_facts(stale_by=timedelta(days=1))
        assert snapshot.updated_at is not None
        assert (datetime.now(timezone.utc) - snapshot.updated_at) >= timedelta(days=1)


class TestMakeEvent:
    def test_the_engine_fold_accepts_it_starting_from_nothing(self) -> None:
        event = make_event(payload={"achieved": True})
        folded = fold_event(None, event)
        assert folded is not None
        assert folded.last_event_id == event["event_id"]
        assert folded.facts["achieved"] is True

    def test_the_engine_fold_accepts_it_on_top_of_a_make_facts_snapshot(self) -> None:
        existing = make_facts(last_event_id="event-1", folded_as_of=datetime.now(timezone.utc) - timedelta(days=1))
        newer = make_event(
            event_id="event-2",
            effective_at=datetime.now(timezone.utc),
            payload={"achieved": True},
        )
        folded = fold_event(existing, newer)
        assert folded is not None
        assert folded.last_event_id == "event-2"
        assert folded.facts["achieved"] is True

    def test_a_redelivered_event_id_folds_to_none(self) -> None:
        existing = make_facts(last_event_id="event-1")
        redelivered = make_event(event_id="event-1")
        assert fold_event(existing, redelivered) is None
