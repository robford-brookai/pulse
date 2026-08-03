"""D16 key derivation — the property the whole idempotency guarantee rests on.

Two obligations, and they pull against each other:

1. **The same fact always derives the same key**, whatever order the payload's keys arrived in,
   whichever process derives it, however the timestamp was spelled. Otherwise a retry after a
   timeout writes a second event.
2. **Distinct facts never derive the same key.** Otherwise a genuinely new fact is answered as a
   replay and is silently lost — the worse of the two failures, because nothing surfaces it.

The golden-digest test is the third obligation: keys are kept forever (D16), so a change to the
derivation splits the key space and every writer's in-flight retry becomes a second event.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from pulse_core.idempotency import (
    NaiveLogicalTimeError,
    UnhashablePayloadError,
    WriterIdError,
    derive_idempotency_key,
)

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

KEY_SHAPE = re.compile(r"^[^:]+:[0-9a-f]{64}$")


def _key(**overrides: object) -> str:
    fields: dict[str, object] = {
        "writer_id": "verdict-relay",
        "subject_type": "referral",
        "subject_key": "ref-1",
        "command_type": "declare_transition",
        "payload": {"to_state": "received"},
        "logical_time": T0,
    }
    fields.update(overrides)
    return derive_idempotency_key(**fields)  # type: ignore[arg-type]


# --- shape -----------------------------------------------------------------------------------


def test_the_key_is_the_writer_id_then_a_sha256_of_the_fact() -> None:
    key = _key()
    assert KEY_SHAPE.match(key)
    writer_id, digest = key.split(":", 1)
    assert writer_id == "verdict-relay"
    assert len(digest) == 64


def test_the_payload_is_hashed_not_carried() -> None:
    """The payload bears PHI once C1 clears; the key is stored forever and travels in logs."""
    key = _key(payload={"note": "synthetic-note-do-not-leak", "to_state": "received"})
    assert "do-not-leak" not in key
    assert "note" not in key


def test_a_writer_id_that_would_make_the_key_ambiguous_is_refused() -> None:
    with pytest.raises(WriterIdError):
        _key(writer_id="verdict:relay")
    with pytest.raises(WriterIdError):
        _key(writer_id="")
    with pytest.raises(WriterIdError):
        _key(writer_id="  ")


# --- the same fact derives the same key -------------------------------------------------------


def test_the_same_fact_derives_the_same_key() -> None:
    assert _key() == _key()


def test_payload_key_order_does_not_change_the_key() -> None:
    flat_a = _key(payload={"to_state": "received", "reason": "referral_intake"})
    flat_b = _key(payload={"reason": "referral_intake", "to_state": "received"})
    assert flat_a == flat_b

    nested_a = _key(payload={"outer": {"a": 1, "b": 2}, "list": [1, 2]})
    nested_b = _key(payload={"list": [1, 2], "outer": {"b": 2, "a": 1}})
    assert nested_a == nested_b


def test_the_same_instant_spelled_in_two_offsets_derives_one_key() -> None:
    other_offset = T0.astimezone(timezone(timedelta(hours=-4)))
    assert other_offset.utcoffset() != T0.utcoffset()
    assert other_offset == T0
    assert _key(logical_time=other_offset) == _key(logical_time=T0)


def test_a_string_logical_time_matching_the_canonical_form_agrees_with_the_datetime() -> None:
    """A writer whose logical clock is already a string is declaring the same fact, not another."""
    assert _key(logical_time="2026-07-01T12:00:00+00:00") == _key(logical_time=T0)


# --- distinct facts never share a key ---------------------------------------------------------


def test_a_new_logical_time_derives_a_new_key() -> None:
    assert _key(logical_time=T0 + timedelta(microseconds=1)) != _key()


def test_every_component_of_the_fact_changes_the_key() -> None:
    baseline = _key()
    assert _key(writer_id="reconciliation") != baseline
    assert _key(subject_type="enrollment") != baseline
    assert _key(subject_key="ref-2") != baseline
    assert _key(command_type="declare_verdict") != baseline
    assert _key(payload={"to_state": "screened"}) != baseline
    assert _key(payload={}) != baseline


def test_component_boundaries_cannot_be_smeared_by_a_value_containing_a_delimiter() -> None:
    """`sha256(subject, command_type, ...)` over concatenated text would collide here."""
    assert _key(subject_type="referral", subject_key="a:b") != _key(subject_type="referral:a", subject_key="b")
    assert _key(subject_key="ref", command_type="a:b") != _key(subject_key="ref:a", command_type="b")


def test_a_payload_value_and_its_string_spelling_are_different_facts() -> None:
    assert _key(payload={"count": 1}) != _key(payload={"count": "1"})
    assert _key(payload={"count": 1.0}) != _key(payload={"count": 1})
    assert _key(payload={"count": 1.5}) == _key(payload={"count": 1.5})
    assert _key(payload={"flag": True}) != _key(payload={"flag": "true"})
    assert _key(payload={"missing": None}) != _key(payload={"missing": "null"})


# --- inputs the derivation refuses ------------------------------------------------------------


def test_a_naive_logical_time_is_refused() -> None:
    with pytest.raises(NaiveLogicalTimeError):
        _key(logical_time=datetime(2026, 7, 1, 12, 0))


def test_a_payload_value_that_is_not_json_native_is_refused_by_path() -> None:
    """A datetime has no single spelling, so serialising it here would invent one per caller."""
    with pytest.raises(UnhashablePayloadError) as raised:
        _key(payload={"observed": {"at": T0}})
    assert raised.value.path == "payload.observed.at"
    assert "datetime" in str(raised.value)
    # And nothing of the value itself, which may be PHI.
    assert "2026" not in str(raised.value)

    with pytest.raises(UnhashablePayloadError) as raised:
        _key(payload={"codes": [{"ok": 1}, {"bad": {1, 2}}]})
    assert raised.value.path == "payload.codes[1].bad"


def test_a_non_finite_number_is_refused() -> None:
    with pytest.raises(UnhashablePayloadError):
        _key(payload={"score": float("nan")})
    with pytest.raises(UnhashablePayloadError):
        _key(payload={"score": float("inf")})


def test_a_non_string_payload_key_is_refused() -> None:
    """JSON has string keys only; `{1: 'a'}` and `{'1': 'a'}` would otherwise be one key."""
    with pytest.raises(UnhashablePayloadError) as raised:
        _key(payload={1: "a"})
    assert raised.value.path == "payload"


# --- the derivation is frozen ------------------------------------------------------------------


def test_the_derivation_is_pinned_to_a_known_digest() -> None:
    """Keys live for the ledger's lifetime, so this test failing is a compatibility break.

    Changing the derivation splits the key space: every retry in flight across the change lands
    as a second event. If it must change, it changes with a documented migration, not silently.
    """
    assert _key() == "verdict-relay:e41030aca1eee7760c7618744f6607bca433e4a4af647d03fde42170935e1d7f"
