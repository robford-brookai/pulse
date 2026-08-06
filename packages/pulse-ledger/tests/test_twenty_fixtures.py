"""Task 1.1: the fixture loader validates fixture shape.

No live network anywhere — every payload here is a file on disk, and this suite only ever reads
it. `twenty_fixtures.py` owns the loading and signing; this file only asserts that what it loads
looks like what `README.md` promises.
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

#: Fixtures whose top-level `eventType` is `record.updated` and which carry a `patientProgram`
#: record — the ones a board mapping could plausibly turn into a command.
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
    def test_it_carries_an_event_id_and_type(self, name: str) -> None:
        body = load_fixture_json(name)
        assert isinstance(body, dict)
        assert isinstance(body["eventId"], str) and body["eventId"]
        assert body["eventType"] in {"record.created", "record.updated", "record.deleted"}

    @pytest.mark.parametrize("name", _PATIENT_PROGRAM_UPDATE_NAMES)
    def test_mapped_board_updates_carry_the_status_field_old_and_new_value(self, name: str) -> None:
        body = load_fixture_json(name)
        assert isinstance(body, dict)
        updated_fields = {field["name"]: field for field in body["updatedFields"]}
        assert "lifecycleStatus" in updated_fields or "qualificationStatus" in updated_fields
        touched = updated_fields.get("lifecycleStatus") or updated_fields["qualificationStatus"]
        assert touched["before"] != touched["after"]


class TestLegalAndIllegalDrag:
    def test_legal_drag_moves_forward_and_carries_the_canonical_id(self) -> None:
        body = load_fixture_json("legal_drag")
        assert isinstance(body, dict)
        field = body["updatedFields"][0]
        assert (field["before"], field["after"]) == ("registered", "enrolled")
        assert body["record"]["patient"]["canonicalPatientId"]
        assert body["workspaceMember"]["id"]

    def test_illegal_drag_moves_backward(self) -> None:
        body = load_fixture_json("illegal_drag")
        assert isinstance(body, dict)
        field = body["updatedFields"][0]
        assert (field["before"], field["after"]) == ("activated", "registered")


class TestRedeliveryDuplicate:
    def test_it_shares_the_legal_drags_event_id(self) -> None:
        legal = load_fixture_json("legal_drag")
        duplicate = load_fixture_json("redelivery_duplicate")
        assert isinstance(legal, dict) and isinstance(duplicate, dict)
        assert duplicate["eventId"] == legal["eventId"]

    def test_it_is_byte_identical_to_the_legal_drag(self) -> None:
        assert load_fixture_bytes("redelivery_duplicate") == load_fixture_bytes("legal_drag")


class TestMissingCanonicalId:
    def test_the_patient_carries_no_canonical_id_field(self) -> None:
        body = load_fixture_json("missing_canonical_id")
        assert isinstance(body, dict)
        assert "canonicalPatientId" not in body["record"]["patient"]
        # It is otherwise a mapped, status-field drag — refused for its missing id, not for
        # looking like noise.
        field = body["updatedFields"][0]
        assert field["name"] == "lifecycleStatus"


class TestNonDragNoise:
    def test_create_has_no_updated_fields(self) -> None:
        body = load_fixture_json("noop_create")
        assert isinstance(body, dict)
        assert body["eventType"] == "record.created"
        assert "updatedFields" not in body

    def test_delete_has_no_updated_fields(self) -> None:
        body = load_fixture_json("noop_delete")
        assert isinstance(body, dict)
        assert body["eventType"] == "record.deleted"
        assert "updatedFields" not in body

    def test_non_status_update_does_not_touch_lifecycle_status(self) -> None:
        body = load_fixture_json("noop_non_status_update")
        assert isinstance(body, dict)
        touched_fields = {field["name"] for field in body["updatedFields"]}
        assert "lifecycleStatus" not in touched_fields
        assert "qualificationStatus" in touched_fields

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

    def test_canary_last_names_are_distinct_per_case_where_the_case_is_a_distinct_person(self) -> None:
        # redelivery_duplicate is deliberately the same person as legal_drag (same delivery,
        # replayed) — every other case is its own synthetic patient.
        distinguishable = [n for n in _PARSEABLE_NAMES if n != "redelivery_duplicate"]
        last_names = set()
        for name in distinguishable:
            body = load_fixture_json(name)
            assert isinstance(body, dict)
            record = body["record"]
            person = record.get("patient", record)
            last_names.add(person["name"]["lastName"])
        assert len(last_names) == len(distinguishable)


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
        signed_at = datetime.fromtimestamp(int(headers[TIMESTAMP_HEADER]), tz=timezone.utc)
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
        signed_at = datetime.fromtimestamp(int(headers[TIMESTAMP_HEADER]), tz=timezone.utc)
        assert signed_at < NOW - SIGNATURE_FRESHNESS
        assert signed_at > NOW - SIGNATURE_FRESHNESS - timedelta(minutes=1)
