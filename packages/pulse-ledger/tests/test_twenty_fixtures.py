"""The fixture loader validates fixture shape — the shape Twenty v2.30 actually sends.

No live network anywhere — every payload here is a file on disk, and this suite only ever reads
it. `twenty_fixtures.py` owns the loading and signing; this file only asserts that what it loads
looks like what `README.md` promises: the captured envelope (`fixtures/twenty/captured/`) bent
along one axis per case.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pulse_ledger.auth import SIGNATURE_FRESHNESS, SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_signature
from twenty_fixtures import (
    FIXTURE_NAMES,
    UnknownFixtureError,
    fixture_path,
    load_fixture_bytes,
    load_fixture_json,
    sign_fixture,
)

NOW = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)

#: Every non-malformed fixture is a JSON object; only `malformed_body` is deliberately not.
_PARSEABLE_NAMES = tuple(name for name in FIXTURE_NAMES if name != "malformed_body")

#: Fixtures whose `eventName` is `patientProgram.updated` — the ones a board mapping could
#: plausibly turn into a command.
_PATIENT_PROGRAM_UPDATE_NAMES = (
    "legal_drag",
    "illegal_drag",
    "redelivery_duplicate",
    "missing_canonical_id",
    "noop_non_status_update",
)


class TestFixtureNames:
    def test_every_named_fixture_file_exists(self) -> None:
        for name in FIXTURE_NAMES:
            assert fixture_path(name).is_file()

    def test_an_unknown_name_is_refused(self) -> None:
        with pytest.raises(UnknownFixtureError):
            fixture_path("not-a-real-case")


class TestParseableFixtureShape:
    @pytest.mark.parametrize("name", _PARSEABLE_NAMES)
    def test_it_parses_as_a_json_object(self, name: str) -> None:
        body = load_fixture_json(name)
        assert isinstance(body, dict)

    @pytest.mark.parametrize("name", _PARSEABLE_NAMES)
    def test_the_discriminator_is_an_object_qualified_event_name(self, name: str) -> None:
        # The captured envelope's discriminator: `eventName` of the form `{object}.{action}`.
        # There is no bare `eventType` and no per-delivery `eventId` — Twenty sends neither.
        body = load_fixture_json(name)
        assert isinstance(body, dict)
        event_name = body["eventName"]
        assert isinstance(event_name, str)
        obj, _, action = event_name.rpartition(".")
        assert obj == body["objectMetadata"]["nameSingular"]
        assert action in {"created", "updated", "deleted"}
        assert "eventType" not in body
        assert "eventId" not in body

    @pytest.mark.parametrize("name", _PARSEABLE_NAMES)
    def test_the_record_is_flat_and_stamped(self, name: str) -> None:
        # The flat ORM entity: scalar/FK fields plus the createdBy/updatedBy actor blocks — no
        # nested related records — and always its own `updatedAt`.
        body = load_fixture_json(name)
        assert isinstance(body, dict)
        record = body["record"]
        assert isinstance(record["id"], str) and record["id"]
        assert isinstance(record["updatedAt"], str) and record["updatedAt"]
        nested = {key for key, value in record.items() if isinstance(value, dict)}
        assert nested <= {"createdBy", "updatedBy"}

    @pytest.mark.parametrize("name", _PATIENT_PROGRAM_UPDATE_NAMES)
    def test_updated_fields_is_a_list_of_field_names(self, name: str) -> None:
        # A string array, never objects with before/after pairs — values live on the record.
        body = load_fixture_json(name)
        assert isinstance(body, dict)
        updated_fields = body["updatedFields"]
        assert isinstance(updated_fields, list) and updated_fields
        assert all(isinstance(entry, str) for entry in updated_fields)
        for entry in updated_fields:
            assert entry in body["record"]


class TestLegalAndIllegalDrag:
    def test_legal_drag_moves_forward_and_carries_the_canonical_id(self) -> None:
        body = load_fixture_json("legal_drag")
        assert isinstance(body, dict)
        assert body["updatedFields"] == ["lifecycleStatus"]
        # The wire value is Twenty's storage encoding of catalog `active` — a legal move from
        # `pending_start`.
        assert body["record"]["lifecycleStatus"] == "ACTIVE"
        assert body["record"]["canonicalPatientId"]
        assert body["record"]["updatedBy"]["workspaceMemberId"]

    def test_illegal_drag_moves_backward(self) -> None:
        body = load_fixture_json("illegal_drag")
        assert isinstance(body, dict)
        # `pending_start` is not reachable from `active` in the catalog's enrollment adjacency.
        assert body["updatedFields"] == ["lifecycleStatus"]
        assert body["record"]["lifecycleStatus"] == "PENDING_START"

    def test_select_values_arrive_in_the_wire_encoding(self) -> None:
        # UPPER_SNAKE on the wire (`encode_option_value`), lowercase in the catalog — asserted so
        # a fixture hand-edited back to catalog vocabulary fails loudly here rather than quietly
        # skewing every downstream suite.
        for name in ("legal_drag", "illegal_drag"):
            body = load_fixture_json(name)
            assert isinstance(body, dict)
            value = body["record"]["lifecycleStatus"]
            assert value == value.upper()


class TestRedeliveryDuplicate:
    def test_it_is_byte_identical_to_the_legal_drag(self) -> None:
        assert load_fixture_bytes("redelivery_duplicate") == load_fixture_bytes("legal_drag")

    def test_it_shares_the_legal_drags_updated_at(self) -> None:
        # There is no delivery id: `record.updatedAt` is the idempotency source (D16), so sharing
        # it is what makes this fixture a redelivery rather than a second drag.
        legal = load_fixture_json("legal_drag")
        duplicate = load_fixture_json("redelivery_duplicate")
        assert isinstance(legal, dict) and isinstance(duplicate, dict)
        assert duplicate["record"]["updatedAt"] == legal["record"]["updatedAt"]


class TestMissingCanonicalId:
    def test_the_record_carries_no_canonical_id_field(self) -> None:
        body = load_fixture_json("missing_canonical_id")
        assert isinstance(body, dict)
        assert "canonicalPatientId" not in body["record"]
        # It is otherwise a mapped, status-field drag — refused for its missing id, not for
        # looking like noise.
        assert body["updatedFields"] == ["lifecycleStatus"]


class TestNonDragNoise:
    def test_create_has_no_updated_fields(self) -> None:
        body = load_fixture_json("noop_create")
        assert isinstance(body, dict)
        assert body["eventName"] == "patientProgram.created"
        assert "updatedFields" not in body

    def test_delete_has_no_updated_fields(self) -> None:
        body = load_fixture_json("noop_delete")
        assert isinstance(body, dict)
        assert body["eventName"] == "patientProgram.deleted"
        assert "updatedFields" not in body

    def test_non_status_update_does_not_touch_lifecycle_status(self) -> None:
        body = load_fixture_json("noop_non_status_update")
        assert isinstance(body, dict)
        assert "lifecycleStatus" not in body["updatedFields"]
        assert "qualificationStatus" in body["updatedFields"]

    def test_unmapped_object_is_not_a_patient_program(self) -> None:
        body = load_fixture_json("noop_unmapped_object")
        assert isinstance(body, dict)
        assert body["objectMetadata"]["nameSingular"] != "patientProgram"


class TestMalformedBody:
    def test_it_does_not_parse_as_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            load_fixture_json("malformed_body")

    def test_its_raw_bytes_still_carry_a_phi_canary(self) -> None:
        """Confirms the fixture is fit for purpose: a handler that logs the unparsed body on a
        malformed request is exactly the leak the PHI scan (`twenty-rejection-feedback` spec,
        "No fixture payload content in logs or receipts across failure paths") must catch."""
        assert b"Canary" in load_fixture_bytes("malformed_body")


class TestPhiCanaries:
    @pytest.mark.parametrize("name", _PARSEABLE_NAMES)
    def test_every_fixture_carries_a_recognizable_fake_demographic(self, name: str) -> None:
        assert b"Canary" in load_fixture_bytes(name)

    def test_canary_titles_are_distinct_per_case_where_the_case_is_a_distinct_record(self) -> None:
        # The flat record's `name` (the card title Twenty stores on the row) is the per-case
        # canary. redelivery_duplicate is deliberately the same record as legal_drag (same
        # delivery, replayed) — every other case is its own synthetic row.
        distinguishable = [n for n in _PARSEABLE_NAMES if n != "redelivery_duplicate"]
        titles = set()
        for name in distinguishable:
            body = load_fixture_json(name)
            assert isinstance(body, dict)
            title = body["record"]["name"]
            assert title.startswith("Canary ")
            titles.add(title)
        assert len(titles) == len(distinguishable)


class TestSignFixture:
    def test_a_valid_signature_verifies(self) -> None:
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture("s3cret-enough-for-a-test-000000", body, now=NOW)
        verify_signature(
            "s3cret-enough-for-a-test-000000",
            body,
            headers[TIMESTAMP_HEADER],
            headers[SIGNATURE_HEADER],
            now=NOW,
        )

    def test_a_tampered_signature_does_not_verify_against_the_original_body(self) -> None:
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture("s3cret-enough-for-a-test-000000", body, now=NOW, kind="tampered")
        with pytest.raises(Exception, match="signature"):
            verify_signature(
                "s3cret-enough-for-a-test-000000",
                body,
                headers[TIMESTAMP_HEADER],
                headers[SIGNATURE_HEADER],
                now=NOW,
            )

    def test_a_stale_signature_is_outside_the_freshness_window(self) -> None:
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture("s3cret-enough-for-a-test-000000", body, now=NOW, kind="stale")
        signed_at = datetime.fromtimestamp(int(headers[TIMESTAMP_HEADER]) / 1000, tz=timezone.utc)
        assert NOW - signed_at > SIGNATURE_FRESHNESS
        with pytest.raises(Exception, match="freshness"):
            verify_signature(
                "s3cret-enough-for-a-test-000000",
                body,
                headers[TIMESTAMP_HEADER],
                headers[SIGNATURE_HEADER],
                now=NOW,
            )

    def test_an_unknown_kind_is_refused(self) -> None:
        body = load_fixture_bytes("legal_drag")
        with pytest.raises(ValueError, match="unknown signature kind"):
            sign_fixture("s3cret-enough-for-a-test-000000", body, now=NOW, kind="bogus")  # type: ignore[arg-type]


class TestStaleTimestampIsBeforeFreshnessCutoff:
    def test_stale_timestamp_predates_now_minus_freshness(self) -> None:
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture("s3cret-enough-for-a-test-000000", body, now=NOW, kind="stale")
        signed_at = datetime.fromtimestamp(int(headers[TIMESTAMP_HEADER]) / 1000, tz=timezone.utc)
        assert signed_at < NOW - SIGNATURE_FRESHNESS
        assert signed_at > NOW - SIGNATURE_FRESHNESS - timedelta(minutes=1)
