"""`billing.facts.fold_event` — the pure fact-fold core (task 3.2).

Pins the two spec scenarios owned by this task: a redelivered event folds once, and two events
delivered out of delivery order fold to the same result regardless of which arrives first,
because ordering is by `effective_at`, never by arrival. Fixture envelopes only — no queue, no
Postgres; sockets are blocked by `conftest.py`.
"""

from __future__ import annotations

import pytest
from billing.facts import SubjectFactsSnapshot, fold_event
from pulse_core.connector import RowValidationError


def envelope(
    *,
    event_id: str = "018f3c2a-0000-7000-8000-000000000001",
    subject_type: str = "billing_episode",
    subject_key: str = "ep-1",
    effective_at: str = "2026-09-01T10:00:00+00:00",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "subject_type": subject_type,
        "subject_key": subject_key,
        "effective_at": effective_at,
        "payload": payload if payload is not None else {"to_state": "qualified"},
    }


def test_first_event_folds_onto_an_empty_snapshot() -> None:
    result = fold_event(None, envelope())
    assert result is not None
    assert result.subject_type == "billing_episode"
    assert result.subject_key == "ep-1"
    assert result.last_event_id == "018f3c2a-0000-7000-8000-000000000001"
    assert result.facts["to_state"] == "qualified"


def test_redelivery_folds_once() -> None:
    first = fold_event(None, envelope())
    assert first is not None

    redelivered = fold_event(first, envelope())

    assert redelivered is None


def test_out_of_order_events_fold_by_effective_time_newer_then_older() -> None:
    newer = envelope(
        event_id="018f3c2a-0000-7000-8000-000000000002",
        effective_at="2026-09-01T12:00:00+00:00",
        payload={"to_state": "qualified"},
    )
    older = envelope(
        event_id="018f3c2a-0000-7000-8000-000000000001",
        effective_at="2026-09-01T09:00:00+00:00",
        payload={"to_state": "open"},
    )

    after_newer = fold_event(None, newer)
    assert after_newer is not None
    after_older = fold_event(after_newer, older)

    assert after_older is None  # the older fact never overwrites the newer one
    assert after_newer.facts["to_state"] == "qualified"


def test_out_of_order_events_fold_by_effective_time_older_then_newer() -> None:
    """Delivered in the opposite order, the two events settle on the same final fact."""
    older = envelope(
        event_id="018f3c2a-0000-7000-8000-000000000001",
        effective_at="2026-09-01T09:00:00+00:00",
        payload={"to_state": "open"},
    )
    newer = envelope(
        event_id="018f3c2a-0000-7000-8000-000000000002",
        effective_at="2026-09-01T12:00:00+00:00",
        payload={"to_state": "qualified"},
    )

    after_older = fold_event(None, older)
    assert after_older is not None
    after_newer = fold_event(after_older, newer)

    assert after_newer is not None
    assert after_newer.facts["to_state"] == "qualified"


def test_a_later_event_merges_onto_the_snapshot_rather_than_replacing_it() -> None:
    """A subsequent event's payload overlays the snapshot; fields it does not touch persist."""
    consent = envelope(
        event_id="018f3c2a-0000-7000-8000-000000000001",
        subject_type="consent",
        effective_at="2026-09-01T09:00:00+00:00",
        payload={"to_state": "granted", "program": "ccm"},
    )
    revoked = envelope(
        event_id="018f3c2a-0000-7000-8000-000000000002",
        subject_type="consent",
        effective_at="2026-09-01T10:00:00+00:00",
        payload={"to_state": "revoked"},
    )

    after_grant = fold_event(None, consent)
    assert after_grant is not None
    after_revoke = fold_event(after_grant, revoked)

    assert after_revoke is not None
    assert after_revoke.facts["to_state"] == "revoked"
    assert after_revoke.facts["program"] == "ccm"  # untouched field survives the merge


@pytest.mark.parametrize("missing_field", ["event_id", "subject_type", "subject_key", "effective_at"])
def test_a_malformed_envelope_names_the_offending_field(missing_field: str) -> None:
    bad = envelope()
    del bad[missing_field]

    with pytest.raises(RowValidationError) as excinfo:
        fold_event(None, bad)

    assert excinfo.value.column == missing_field


def test_a_non_object_payload_is_rejected_by_column_name() -> None:
    bad = envelope()
    bad["payload"] = "not-an-object"

    with pytest.raises(RowValidationError) as excinfo:
        fold_event(None, bad)

    assert excinfo.value.column == "payload"


def test_snapshot_folded_as_of_reads_the_reserved_key() -> None:
    result = fold_event(None, envelope(effective_at="2026-09-01T10:00:00+00:00"))
    assert isinstance(result, SubjectFactsSnapshot)
    assert result.folded_as_of == "2026-09-01T10:00:00+00:00"
