"""Canonical request v1 and the authenticated writer binding (idempotency-integrity 1.1).

Three scenarios of the command-api delta land here (`traceability.json`):

- *Distinct facts never share a key* — a semantically different accepted request fingerprints
  differently, so the binding refuses to answer it with the original result.
- *Canonical exact retry remains compatible* — object-key order and equivalent UTC spellings are
  normalised away, list order and distinct values are not, and no client-only `logical_time` is
  reconstructed from `effective_at`.
- *Fingerprint versions and telemetry preserve integrity* — the field set is frozen under `v1` and
  the version is inside the digest, and nothing a request carried reaches a log line.

Every declaration is built through the real boundary (`declaration_from_request`), so a vector
proves what the API would fingerprint, not what a hand-built dataclass would. Fixtures are
synthetic: `enrollment` subjects with invented keys, never a real patient.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pulse_ledger.api import WEBHOOK_WRITER, declaration_from_request
from pulse_ledger.auth import BACKFILL_ACTOR_ID, Writer
from pulse_ledger.commit import Declaration
from pulse_ledger.request_fingerprint import (
    CANONICAL_FIELDS_V1,
    EXCLUDED_FIELDS_V1,
    FINGERPRINT_VERSION,
    BindingDisposition,
    UnfingerprintableValueError,
    UnknownFingerprintVersionError,
    WriterBinding,
    bind_request,
    canonical_request,
    classify_binding,
    request_fingerprint,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "request_fingerprint_v1_golden.json"

SUBJECT_KEY = "enrollment-synthetic-0001"
CONNECTOR = Writer(writer_id="clinic-connector", actor_authority="connector")
BATCH_WRITER = Writer(writer_id=BACKFILL_ACTOR_ID, actor_authority="backfill")
OTHER_WRITER = Writer(writer_id="reconciliation")

#: The principals the canonical request is computed under. Named here because the binding is what
#: separates them: the request bytes are identical across all three.
PRINCIPALS: dict[str, Writer] = {
    "bearer": CONNECTOR,
    "batch": BATCH_WRITER,
    "webhook": WEBHOOK_WRITER,
}


def body(**overrides: Any) -> dict[str, Any]:
    request = {
        "subject_type": "enrollment",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_transition",
        "to_state": "on_hold",
        "effective_at": "2026-08-03T11:59:00+00:00",
        "payload": {"hold_reason": "awaiting_authorization"},
    }
    request.update(overrides)
    return request


def fingerprint_of(request: dict[str, Any], writer: Writer = CONNECTOR) -> str:
    return request_fingerprint(declaration_from_request(request, writer))


def key_for(writer: Writer, digest: str = "a" * 64) -> str:
    return f"{writer.writer_id}:{digest}"


def with_payload(payload: Mapping[str, Any]) -> Declaration:
    """The baseline declaration carrying a payload no JSON body could have delivered.

    The webhook mapping builds declarations in-process, so a payload really can hold a `datetime`,
    a `UUID`, or something with no canonical spelling at all — none of which survives a round trip
    through `json.loads`, and all of which the fingerprint has to answer for.
    """
    declaration = declaration_from_request(body(), CONNECTOR)
    return replace(declaration, payload=payload)


class TestCanonicalExactRetryRemainsCompatible:
    """command-api/Canonical exact retry remains compatible."""

    def test_object_key_order_does_not_change_the_fingerprint(self) -> None:
        reordered = dict(reversed(list(body().items())))
        reordered["payload"] = {"note": "reordered", "hold_reason": "awaiting_authorization"}
        original = body(payload={"hold_reason": "awaiting_authorization", "note": "reordered"})
        assert fingerprint_of(reordered) == fingerprint_of(original)

    @pytest.mark.parametrize(
        "spelling",
        [
            "2026-08-03T11:59:00+00:00",
            "2026-08-03T11:59:00Z",
            "2026-08-03T11:59:00-00:00",
            "2026-08-03T13:59:00+02:00",
            "2026-08-03T06:59:00-05:00",
        ],
    )
    def test_equivalent_utc_spellings_share_one_fingerprint(self, spelling: str) -> None:
        assert fingerprint_of(body(effective_at=spelling)) == fingerprint_of(body())

    def test_the_occurred_at_alias_shares_the_canonical_fields_fingerprint(self) -> None:
        aliased = body()
        aliased["occurred_at"] = aliased.pop("effective_at")
        assert fingerprint_of(aliased) == fingerprint_of(body())

    def test_list_order_is_semantic_and_changes_the_fingerprint(self) -> None:
        forward = body(payload={"codes": ["A", "B"]})
        reversed_ = body(payload={"codes": ["B", "A"]})
        assert fingerprint_of(forward) != fingerprint_of(reversed_)

    def test_client_only_logical_time_is_not_part_of_the_canonical_request(self) -> None:
        """The SDK key hashes a `logical_time` the server never receives (design decision 2).

        The canonical field map therefore names no such field, so the boundary never has to
        reconstruct one from `effective_at` to answer a valid retry.
        """
        assert "logical_time" not in CANONICAL_FIELDS_V1
        assert "logical_time" in EXCLUDED_FIELDS_V1

    @pytest.mark.parametrize("excluded", sorted(EXCLUDED_FIELDS_V1 - {"logical_time"}))
    def test_no_excluded_field_appears_in_the_canonical_request(self, excluded: str) -> None:
        assert excluded not in canonical_request(declaration_from_request(body(), CONNECTOR))

    def test_tracing_identifiers_do_not_change_the_fingerprint(self) -> None:
        traced = body(correlation_id=str(uuid.uuid4()), causation_id=str(uuid.uuid4()))
        assert fingerprint_of(traced) == fingerprint_of(body())

    def test_the_same_request_under_two_principals_has_one_fingerprint(self) -> None:
        """The request is the request; who sent it lives in the binding, not the digest."""
        fingerprints = {name: fingerprint_of(body(), writer) for name, writer in PRINCIPALS.items()}
        assert len(set(fingerprints.values())) == 1, fingerprints


class TestDistinctFactsNeverShareAKey:
    """command-api/Distinct facts never share a key."""

    @pytest.mark.parametrize(
        ("name", "changed"),
        [
            ("effective_at", {"effective_at": "2026-08-03T12:00:00+00:00"}),
            ("subject_key", {"subject_key": "enrollment-synthetic-0002"}),
            ("subject_type", {"subject_type": "referral"}),
            ("event_type", {"event_type": "declare_hold"}),
            ("to_state", {"to_state": "active"}),
            ("payload_value", {"payload": {"hold_reason": "awaiting_records"}}),
            ("payload_field", {"payload": {"hold_reason": "awaiting_authorization", "extra": 1}}),
            ("evidence", {"evidence": {"source_document": "synthetic-fax-0001"}}),
            ("evidence_class", {"evidence_class": "E1"}),
            ("epoch", {"epoch": "reconstructed"}),
            (
                "evidence_bounds",
                {"evidence_bounds": ["2026-08-01T00:00:00+00:00", "2026-08-02T00:00:00+00:00"]},
            ),
        ],
    )
    def test_a_changed_semantic_field_changes_the_fingerprint(self, name: str, changed: dict[str, Any]) -> None:
        assert fingerprint_of(body(**changed)) != fingerprint_of(body()), name

    def test_a_string_and_its_number_are_distinguishable(self) -> None:
        assert fingerprint_of(body(payload={"count": 1})) != fingerprint_of(body(payload={"count": "1"}))

    def test_a_null_payload_field_differs_from_an_absent_one(self) -> None:
        assert fingerprint_of(body(payload={"hold_reason": None})) != fingerprint_of(body(payload={}))

    def test_field_boundaries_do_not_smear(self) -> None:
        """A concatenated pre-image would collide these two; a JSON object with named members
        has no delimiter to move."""
        left = body(subject_key="ab", payload={})
        right = body(subject_key="a", payload={})
        right["subject_type"] = "enrollmentb"
        assert fingerprint_of(left) != fingerprint_of(right)


class TestAuthenticatedWriterBinding:
    """Decision 1: identity comes from the credential, never from the key's text."""

    def test_the_binding_takes_its_writer_from_the_credential_not_the_key_prefix(self) -> None:
        binding = bind_request(
            idempotency_key=key_for(OTHER_WRITER),
            writer=CONNECTOR,
            declaration=declaration_from_request(body(), CONNECTOR),
        )
        assert binding.writer_id == CONNECTOR.writer_id

    def test_an_exact_retry_by_the_same_writer_is_a_replay(self) -> None:
        existing = bind_request(
            idempotency_key=key_for(CONNECTOR),
            writer=CONNECTOR,
            declaration=declaration_from_request(body(), CONNECTOR),
            event_id=uuid.uuid4(),
        )
        assert (
            classify_binding(existing, writer_id=CONNECTOR.writer_id, fingerprint=fingerprint_of(body()))
            is BindingDisposition.REPLAY
        )

    def test_another_authenticated_writer_reusing_the_key_conflicts(self) -> None:
        existing = bind_request(
            idempotency_key=key_for(CONNECTOR),
            writer=CONNECTOR,
            declaration=declaration_from_request(body(), CONNECTOR),
            event_id=uuid.uuid4(),
        )
        assert (
            classify_binding(existing, writer_id=OTHER_WRITER.writer_id, fingerprint=fingerprint_of(body()))
            is BindingDisposition.CONFLICT
        )

    def test_the_same_writer_with_different_content_conflicts(self) -> None:
        existing = bind_request(
            idempotency_key=key_for(CONNECTOR),
            writer=CONNECTOR,
            declaration=declaration_from_request(body(), CONNECTOR),
            event_id=uuid.uuid4(),
        )
        changed = fingerprint_of(body(payload={"hold_reason": "awaiting_records"}))
        assert (
            classify_binding(existing, writer_id=CONNECTOR.writer_id, fingerprint=changed)
            is BindingDisposition.CONFLICT
        )

    def test_a_fingerprint_from_another_version_never_matches(self) -> None:
        existing = WriterBinding(
            idempotency_key=key_for(CONNECTOR),
            writer_id=CONNECTOR.writer_id,
            fingerprint="v0:" + "b" * 64,
            event_id=uuid.uuid4(),
        )
        assert (
            classify_binding(existing, writer_id=CONNECTOR.writer_id, fingerprint=fingerprint_of(body()))
            is BindingDisposition.CONFLICT
        )

    def test_an_unclaimed_key_is_free_to_claim(self) -> None:
        assert (
            classify_binding(None, writer_id=CONNECTOR.writer_id, fingerprint=fingerprint_of(body()))
            is BindingDisposition.UNCLAIMED
        )

    def test_batch_and_webhook_principals_do_not_share_a_binding(self) -> None:
        """Same bytes, three principals: only the one that claimed the key replays."""
        claimed = bind_request(
            idempotency_key=key_for(BATCH_WRITER),
            writer=BATCH_WRITER,
            declaration=declaration_from_request(body(), BATCH_WRITER),
            event_id=uuid.uuid4(),
        )
        fingerprint = fingerprint_of(body())
        assert classify_binding(claimed, writer_id=BATCH_WRITER.writer_id, fingerprint=fingerprint) is (
            BindingDisposition.REPLAY
        )
        assert classify_binding(claimed, writer_id=WEBHOOK_WRITER.writer_id, fingerprint=fingerprint) is (
            BindingDisposition.CONFLICT
        )


class TestFingerprintVersionsAndTelemetry:
    """command-api/Fingerprint versions and telemetry preserve integrity."""

    def test_the_fingerprint_carries_its_version(self) -> None:
        fingerprint = fingerprint_of(body())
        version, _, digest = fingerprint.partition(":")
        assert version == FINGERPRINT_VERSION
        assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")

    def test_the_version_is_inside_the_digest_not_only_its_label(self) -> None:
        """A field-set change needs a new version, and a new version must not be forgeable by
        relabelling an old digest — so the version is part of what is hashed."""
        declaration = declaration_from_request(body(), CONNECTOR)
        canonical = canonical_request(declaration)
        assert canonical["fingerprint_version"] == FINGERPRINT_VERSION

    def test_an_unknown_version_is_refused_rather_than_guessed(self) -> None:
        declaration = declaration_from_request(body(), CONNECTOR)
        with pytest.raises(UnknownFingerprintVersionError):
            request_fingerprint(declaration, version="v2")

    def test_the_v1_field_set_is_frozen(self) -> None:
        """This assertion is the version gate: changing the field map fails here, and the fix is a
        new version beside v1, never an edit to v1."""
        assert CANONICAL_FIELDS_V1 == (
            "subject_type",
            "subject_key",
            "event_type",
            "to_state",
            "effective_at",
            "epoch",
            "evidence_class",
            "evidence",
            "evidence_bounds",
            "payload",
        )

    def test_the_canonical_request_holds_exactly_the_versioned_field_set(self) -> None:
        canonical = canonical_request(declaration_from_request(body(), CONNECTOR))
        assert set(canonical) == {*CANONICAL_FIELDS_V1, "fingerprint_version"}

    def test_the_binding_repr_leaks_neither_fingerprint_nor_request(self) -> None:
        rendered = repr(
            bind_request(
                idempotency_key=key_for(CONNECTOR),
                writer=CONNECTOR,
                declaration=declaration_from_request(body(payload={"hold_reason": "secret-synthetic"}), CONNECTOR),
            )
        )
        assert "secret-synthetic" not in rendered
        assert fingerprint_of(body(payload={"hold_reason": "secret-synthetic"})).split(":")[1] not in rendered

    def test_telemetry_fields_are_identifiers_and_codes_only(self) -> None:
        binding = bind_request(
            idempotency_key=key_for(CONNECTOR),
            writer=CONNECTOR,
            declaration=declaration_from_request(body(payload={"hold_reason": "secret-synthetic"}), CONNECTOR),
            event_id=uuid.uuid4(),
        )
        facts = binding.telemetry_fields()
        assert set(facts) == {"idempotency_key", "writer_id", "fingerprint_version", "event_id"}
        rendered = json.dumps(facts, default=str)
        assert "secret-synthetic" not in rendered
        assert binding.fingerprint.split(":")[1] not in rendered

    def test_a_value_with_no_canonical_spelling_is_named_by_path_not_by_value(self) -> None:
        offending = object()
        with pytest.raises(UnfingerprintableValueError) as raised:
            request_fingerprint(with_payload({"hold_reason": offending}))
        assert "payload.hold_reason" in str(raised.value)
        assert repr(offending) not in str(raised.value)

    @pytest.mark.parametrize(
        ("payload", "path", "type_name"),
        [
            ({"score": float("nan")}, "payload.score", "non-finite float"),
            ({"score": float("inf")}, "payload.score", "non-finite float"),
            ({"observed_at": datetime(2026, 8, 3, 11, 59)}, "payload.observed_at", "naive datetime"),
            ({"codes": [object()]}, "payload.codes[0]", "object"),
            ({"by_number": {1: "one"}}, "payload.by_number", "mapping with a int key"),
        ],
    )
    def test_every_unfingerprintable_value_is_reported_by_path_and_type(
        self, payload: dict[str, Any], path: str, type_name: str
    ) -> None:
        """Each branch names where and what, never the value — `payload` carries PHI once C1 clears."""
        with pytest.raises(UnfingerprintableValueError) as raised:
            request_fingerprint(with_payload(payload))
        assert raised.value.path == path
        assert raised.value.type_name == type_name


class TestGoldenVectors:
    """The versioned golden vectors design.md's risk register calls for.

    A change to normalisation that these do not catch is a change that silently re-keys every
    deployed producer's retries; regenerate them only alongside a new fingerprint version.
    """

    @staticmethod
    def load() -> dict[str, Any]:
        return json.loads(GOLDEN_PATH.read_text())

    def test_the_vectors_are_recorded_for_this_version(self) -> None:
        assert self.load()["fingerprint_version"] == FINGERPRINT_VERSION

    def test_every_vector_still_fingerprints_to_its_recorded_digest(self) -> None:
        mismatched = {}
        for vector in self.load()["vectors"]:
            writer = PRINCIPALS[vector["principal"]]
            actual = request_fingerprint(declaration_from_request(dict(vector["request"]), writer))
            if actual != vector["fingerprint"]:
                mismatched[vector["name"]] = (vector["fingerprint"], actual)
        assert not mismatched, f"canonical request v1 has drifted: {mismatched}"

    def test_the_vectors_cover_every_named_normalisation_class(self) -> None:
        covered = {vector["covers"] for vector in self.load()["vectors"]}
        assert covered >= {
            "utc_alias",
            "key_order",
            "list_order",
            "payload_change",
            "evidence_change",
            "batch_principal",
            "webhook_principal",
        }

    def test_the_vectors_carry_no_timestamp_of_their_own_generation(self) -> None:
        """A generated-at stamp would make the file churn on every regeneration and hide a real
        digest change in the diff."""
        assert "generated_at" not in self.load()

    def test_aliased_vectors_agree_and_distinct_ones_differ(self) -> None:
        by_name = {vector["name"]: vector for vector in self.load()["vectors"]}
        assert by_name["utc_alias_zulu"]["fingerprint"] == by_name["baseline"]["fingerprint"]
        assert by_name["utc_alias_offset"]["fingerprint"] == by_name["baseline"]["fingerprint"]
        assert by_name["key_order_swapped"]["fingerprint"] == by_name["key_order_declared"]["fingerprint"]
        assert by_name["list_order_reversed"]["fingerprint"] != by_name["list_order_declared"]["fingerprint"]
        assert by_name["payload_value_changed"]["fingerprint"] != by_name["baseline"]["fingerprint"]
        assert by_name["evidence_added"]["fingerprint"] != by_name["baseline"]["fingerprint"]
        assert by_name["batch_principal"]["fingerprint"] == by_name["baseline"]["fingerprint"]
        assert by_name["webhook_principal"]["fingerprint"] == by_name["baseline"]["fingerprint"]


def test_a_naive_effective_at_never_reaches_the_fingerprint() -> None:
    """`Declaration.__post_init__` already refuses it; asserted here so the normalisation below
    can assume an aware datetime rather than inventing a UTC one."""
    with pytest.raises(ValueError, match="timezone-aware"):
        declaration_from_request(body(effective_at="2026-08-03T11:59:00"), CONNECTOR)


def test_a_payload_datetime_is_normalised_the_same_way_a_field_one_is() -> None:
    """The webhook mapping builds declarations in-process, so a payload may hold a real
    `datetime` that never passed through JSON."""
    instant = datetime(2026, 8, 3, 11, 59, tzinfo=timezone.utc)
    offset = instant.astimezone(timezone(timedelta(hours=2)))
    assert request_fingerprint(with_payload({"observed_at": instant})) == request_fingerprint(
        with_payload({"observed_at": offset})
    )


def test_a_payload_uuid_fingerprints_as_its_canonical_text() -> None:
    """Same reason as the datetime: an in-process declaration may hold the object, a JSON one its
    string, and the two are one request."""
    identifier = uuid.uuid4()
    assert request_fingerprint(with_payload({"record_id": identifier})) == request_fingerprint(
        with_payload({"record_id": str(identifier)})
    )


def test_a_finite_float_is_fingerprintable() -> None:
    assert request_fingerprint(with_payload({"score": 0.5})) != request_fingerprint(with_payload({"score": 0.6}))
