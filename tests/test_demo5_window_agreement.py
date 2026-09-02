"""Unit tests for Demo 5 stage 5 (task 2.2): the shape reducer, the three window readers, and the
comparison that fails on any disagreement.

No compose stack, no LocalStack, no real Twenty — each window reader is exercised against a fake
of exactly the dependency it needs (a canned SQS-shaped stub, an in-memory board double, plain
envelope dicts), per the demo's own smoke-parse/harness-unit convention
(`test_demo5_end_to_end.py`'s module docstring).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo5_end_to_end.py"

spec = importlib.util.spec_from_file_location("demo5_end_to_end", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo5 = importlib.util.module_from_spec(spec)
sys.modules["demo5_end_to_end"] = demo5
spec.loader.exec_module(demo5)


def _envelope(
    *,
    subject_type: str = "communication_consent",
    subject_key: str = "brook-fx-demo5-episode-0001",
    to_state: str | None = "opted_in",
    program: str | None = None,
    effective_at: datetime = datetime(2026, 8, 1, tzinfo=UTC),
    recorded_at: datetime = datetime(2026, 8, 1, 0, 1, tzinfo=UTC),
    reverses_event_id: str | None = None,
    seq: int = 1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if to_state is not None:
        payload["to_state"] = to_state
    if program is not None:
        payload["program"] = program
    return {
        "event_id": str(uuid.uuid4()),
        "subject_type": subject_type,
        "subject_key": subject_key,
        "seq": seq,
        "effective_at": effective_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "reverses_event_id": reverses_event_id,
        "payload": payload,
    }


# --- The reducer -------------------------------------------------------------------------------


def test_reduce_normalizes_as_of_to_utc_isoformat() -> None:
    as_of = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    tup = demo5._reduce("communication_consent", "subject-1", "opted_in", as_of)
    assert tup == ("communication_consent", "subject-1", "opted_in", "2026-08-01T12:00:00+00:00")


# --- _fold_envelopes: the independent-fold and warehouse windows share this --------------------


def test_fold_envelopes_folds_a_forward_history_to_its_last_state() -> None:
    events = [
        _envelope(to_state="unset", effective_at=datetime(2026, 8, 1, tzinfo=UTC)),
        _envelope(to_state="opted_in", effective_at=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    tup = demo5._fold_envelopes("communication_consent", "subject-1", events)
    assert tup == ("communication_consent", "subject-1", "opted_in", "2026-08-02T00:00:00+00:00")


def test_fold_envelopes_drops_a_reversed_event() -> None:
    reversed_id = str(uuid.uuid4())
    events = [
        {**_envelope(to_state="opted_in", effective_at=datetime(2026, 8, 2, tzinfo=UTC)), "event_id": reversed_id},
        _envelope(to_state=None, reverses_event_id=reversed_id, effective_at=datetime(2026, 8, 3, tzinfo=UTC)),
        _envelope(to_state="unset", effective_at=datetime(2026, 8, 1, tzinfo=UTC)),
    ]
    tup = demo5._fold_envelopes("communication_consent", "subject-1", events)
    assert tup == ("communication_consent", "subject-1", "unset", "2026-08-01T00:00:00+00:00")


def test_fold_envelopes_with_no_state_bearing_events_returns_none() -> None:
    assert demo5._fold_envelopes("communication_consent", "subject-1", []) is None


# --- _check_window_agrees: the comparison, and its PHI tripwire ---------------------------------


def test_check_window_agrees_passes_on_a_matching_tuple() -> None:
    ledger = ("communication_consent", "subject-1", "opted_in", "2026-08-01T00:00:00+00:00")
    demo5._check_window_agrees(
        stage="window_agreement", subject_key="subject-1", window="fold", ledger=ledger, observed=ledger
    )  # no raise


def test_check_window_agrees_names_stage_subject_and_field_never_a_value() -> None:
    sensitive_marker = "AC1V3-PHI-MARKER-DO-NOT-LEAK"
    ledger = ("communication_consent", "subject-1", sensitive_marker, "2026-08-01T00:00:00+00:00")
    observed = ("communication_consent", "subject-1", "a-different-state", "2026-08-01T00:00:00+00:00")

    with pytest.raises(demo5.DemoAssertionError) as excinfo:
        demo5._check_window_agrees(
            stage="window_agreement", subject_key="subject-1", window="fold", ledger=ledger, observed=observed
        )

    message = str(excinfo.value)
    assert "window_agreement" in message
    assert "subject-1" in message
    assert "'state'" in message
    # The PHI tripwire: neither disagreeing value ever reaches the message.
    assert sensitive_marker not in message
    assert "a-different-state" not in message


def test_check_window_agrees_reports_a_missing_window_as_the_state_field() -> None:
    ledger = ("communication_consent", "subject-1", "opted_in", "2026-08-01T00:00:00+00:00")
    with pytest.raises(demo5.DemoAssertionError) as excinfo:
        demo5._check_window_agrees(
            stage="window_agreement", subject_key="subject-1", window="warehouse", ledger=ledger, observed=None
        )
    assert "'state'" in str(excinfo.value)
    assert "opted_in" not in str(excinfo.value)


# --- _drain_landed_events: the warehouse window's source, against a canned SQS-shaped stub -----


class _FakeSqs:
    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self._batches = list(batches)

    def receive_message(self, *, QueueUrl: str, WaitTimeSeconds: int, MaxNumberOfMessages: int) -> dict[str, Any]:
        del QueueUrl, WaitTimeSeconds, MaxNumberOfMessages
        messages = self._batches.pop(0) if self._batches else []
        return {"Messages": messages}


def _message(detail: dict[str, Any]) -> dict[str, Any]:
    import json

    return {"Body": json.dumps({"detail": detail})}


def test_drain_landed_events_collects_only_wanted_subjects() -> None:
    wanted_envelope = _envelope(subject_type="billing_episode", subject_key="episode-1")
    unwanted_envelope = _envelope(subject_type="billing_episode", subject_key="episode-other")
    sqs = _FakeSqs([[_message(wanted_envelope), _message(unwanted_envelope)], [], []])

    landed = demo5._drain_landed_events(sqs, "http://queue", frozenset({("billing_episode", "episode-1")}), timeout=5.0)

    assert [e["subject_key"] for e in landed[("billing_episode", "episode-1")]] == ["episode-1"]


def test_drain_landed_events_stops_after_two_idle_polls_without_the_full_timeout() -> None:
    sqs = _FakeSqs([[], []])
    landed = demo5._drain_landed_events(
        sqs, "http://queue", frozenset({("billing_episode", "episode-1")}), timeout=30.0
    )
    assert landed == {("billing_episode", "episode-1"): []}


# --- _board_state and _BoardDouble: the board window, against the real apply.py core -----------


def test_board_double_seed_then_apply_then_read_back() -> None:
    store = demo5._BoardDouble()
    store.seed("demo5-board-patient-1", {"canonicalPatientId": "patient-1", "programCode": "demo5"})
    transport = store.transport()

    events = [
        _envelope(
            subject_type="enrollment",
            subject_key="patient-1",
            to_state="pending_start",
            program="demo5",
            effective_at=datetime(2026, 8, 1, tzinfo=UTC),
            seq=1,
        ),
        _envelope(
            subject_type="enrollment",
            subject_key="patient-1",
            to_state="active",
            program="demo5",
            effective_at=datetime(2026, 8, 2, tzinfo=UTC),
            seq=2,
        ),
    ]

    tup = demo5._board_state(
        events,
        transport=transport,
        base_url="http://demo5-board.local",
        store=store,
        subject_key="patient-1",
    )

    assert tup == ("enrollment", "patient-1", "active", "2026-08-02T00:00:00+00:00")


def test_board_state_skips_reversal_events() -> None:
    store = demo5._BoardDouble()
    store.seed("demo5-board-patient-1", {"canonicalPatientId": "patient-1", "programCode": "demo5"})
    transport = store.transport()

    genesis_id = str(uuid.uuid4())
    events = [
        {
            **_envelope(
                subject_type="enrollment",
                subject_key="patient-1",
                to_state="pending_start",
                program="demo5",
                effective_at=datetime(2026, 8, 1, tzinfo=UTC),
                seq=1,
            ),
            "event_id": genesis_id,
        },
        # A reversal envelope: no to_state, would fail apply.py's parse if not skipped.
        _envelope(
            subject_type="enrollment",
            subject_key="patient-1",
            to_state=None,
            program="demo5",
            reverses_event_id=genesis_id,
            effective_at=datetime(2026, 8, 2, tzinfo=UTC),
            seq=2,
        ),
    ]

    tup = demo5._board_state(
        events, transport=transport, base_url="http://demo5-board.local", store=store, subject_key="patient-1"
    )
    assert tup is not None
    assert tup[2] == "pending_start"


def test_board_state_returns_none_when_the_record_was_never_written() -> None:
    store = demo5._BoardDouble()
    store.seed("demo5-board-patient-1", {"canonicalPatientId": "patient-1", "programCode": "demo5"})
    tup = demo5._board_state(
        [], transport=store.transport(), base_url="http://demo5-board.local", store=store, subject_key="patient-1"
    )
    assert tup is None


def test_parse_filter_round_trips_find_records_grammar() -> None:
    assert demo5._parse_filter("canonicalPatientId[eq]:patient-1,programCode[eq]:demo5") == {
        "canonicalPatientId": "patient-1",
        "programCode": "demo5",
    }
    assert demo5._parse_filter("") == {}


# --- The stage is wired last, after the producing stages ---------------------------------------


def test_window_agreement_stage_is_last() -> None:
    assert demo5.STAGES[-1].name == "window_agreement"
