"""Task 2.1: the pure drag → command core.

Every case here is one of task 1.1's synthetic fixtures run through `interpret`. Nothing in this
file builds an app, opens a socket, or touches a committer — that is the point of the module under
test being pure, and it is what lets the retrofit-expensive decisions (which subject, which state,
which logical time) be pinned by cheap tests.

PHI posture: the fixtures carry recognizable fakes (`Canary <Case>`), so the scans below can assert
that no demographic string reaches a declaration, an evidence block, or a disposition's repr.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pulse_core.idempotency import derive_idempotency_key
from pulse_ledger.twenty.mapping import (
    DRAG_COMMAND_TYPE,
    NOOP_NOT_A_RECORD_UPDATE,
    NOOP_STATUS_FIELD_UNTOUCHED,
    NOOP_UNMAPPED_OBJECT,
    TWENTY_EVIDENCE_SYSTEM,
    V1_BOARD_MAPPINGS,
    WEBHOOK_WRITER_ID,
    BoardMapping,
    Drag,
    MalformedPayloadError,
    NoOp,
    RecordRef,
    Unmapped,
    interpret,
)
from twenty_fixtures import load_fixture_json

PATIENT_PROGRAM_BOARD = V1_BOARD_MAPPINGS[0]

#: Demographic strings a leak would carry out of the payload. `Canary` alone would match every
#: fixture; the surname is what identifies which one leaked.
DEMOGRAPHIC_STRINGS = ("Canary", "LegalDrag", "IllegalDrag", "MissingCanonical", "CareCoordinator")


def payload(name: str) -> dict[str, object]:
    body = load_fixture_json(name)
    assert isinstance(body, dict)
    return body


def drag(name: str) -> Drag:
    disposition = interpret(payload(name), V1_BOARD_MAPPINGS)
    assert isinstance(disposition, Drag), f"{name} did not map to a Drag: {disposition!r}"
    return disposition


class TestOnlyMappedDragsBecomeCommands:
    """Spec: "A status-field update on a mapped board yields one command"."""

    def test_a_status_field_update_on_a_mapped_board_yields_one_declaration(self) -> None:
        disposition = drag("legal_drag")
        assert disposition.declaration_fields["event_type"] == DRAG_COMMAND_TYPE
        assert disposition.declaration_fields["to_state"] == "enrolled"

    def test_the_target_state_is_the_new_column_not_the_old_one(self) -> None:
        # `illegal_drag` moves backwards (`activated` → `registered`); the mapping declares the
        # column dragged *to* and leaves legality to the catalog.
        assert drag("illegal_drag").declaration_fields["to_state"] == "registered"

    def test_effective_at_is_the_payloads_update_time(self) -> None:
        assert drag("legal_drag").declaration_fields["effective_at"] == datetime(2026, 8, 6, 15, 4, tzinfo=timezone.utc)

    def test_the_card_and_member_refs_name_the_twenty_records(self) -> None:
        disposition = drag("legal_drag")
        assert disposition.card_ref == RecordRef("patientProgram", "twenty-record-patientprogram-0001")
        assert disposition.member_ref == "workspaceMember:wsm-0001-canary-nurse"

    def test_evidence_carries_the_member_and_record_refs_and_no_record_fields(self) -> None:
        evidence = drag("legal_drag").declaration_fields["evidence"]
        assert evidence == {
            "system": TWENTY_EVIDENCE_SYSTEM,
            "ref": "workspaceMember:wsm-0001-canary-nurse",
            "record_ref": "patientProgram:twenty-record-patientprogram-0001",
        }

    def test_the_declaration_names_no_actor(self) -> None:
        # Attribution is the route's (decision 2): a constant `Writer` stamps it, and
        # `Writer.attribute` raises `ActorSpoofError` on a body that already carries one.
        fields = drag("legal_drag").declaration_fields
        for credential_derived in ("actor_type", "actor_id", "actor_authority", "producer"):
            assert credential_derived not in fields

    def test_the_program_travels_in_the_payload_not_the_subject_key(self) -> None:
        assert drag("legal_drag").declaration_fields["payload"] == {"program": "diabetes-mgmt"}


class TestNonDragNotificationsAreNoOps:
    """Spec: "A non-drag notification is acknowledged as a no-op"."""

    @pytest.mark.parametrize(
        ("name", "reason"),
        [
            ("noop_create", NOOP_NOT_A_RECORD_UPDATE),
            ("noop_delete", NOOP_NOT_A_RECORD_UPDATE),
            ("noop_non_status_update", NOOP_STATUS_FIELD_UNTOUCHED),
            ("noop_unmapped_object", NOOP_UNMAPPED_OBJECT),
        ],
    )
    def test_a_non_drag_notification_is_a_noop_with_a_coded_reason(self, name: str, reason: str) -> None:
        disposition = interpret(payload(name), V1_BOARD_MAPPINGS)
        assert disposition == NoOp(reason)

    def test_a_noop_reason_is_a_fixed_code_carrying_no_payload_content(self) -> None:
        for name in ("noop_create", "noop_delete", "noop_non_status_update", "noop_unmapped_object"):
            reason = interpret(payload(name), V1_BOARD_MAPPINGS).reason  # type: ignore[union-attr]
            assert reason in {NOOP_NOT_A_RECORD_UPDATE, NOOP_STATUS_FIELD_UNTOUCHED, NOOP_UNMAPPED_OBJECT}

    def test_no_mappings_at_all_makes_every_object_unmapped(self) -> None:
        assert interpret(payload("legal_drag"), ()) == NoOp(NOOP_UNMAPPED_OBJECT)


class TestTheCanonicalIdentifierResolvesTheSubject:
    """Spec: "The canonical identifier resolves the subject"."""

    def test_subject_type_and_key_come_from_the_mapping_and_the_canonical_id(self) -> None:
        fields = drag("legal_drag").declaration_fields
        assert fields["subject_type"] == PATIENT_PROGRAM_BOARD.subject_type
        assert fields["subject_key"] == "DIM_PATIENT_CONFORMED-000101"

    def test_no_twenty_record_id_is_ever_a_subject_key(self) -> None:
        record = payload("legal_drag")["record"]
        assert isinstance(record, dict)
        twenty_ids = {record["id"], record["patient"]["id"], record["program"]["id"]}  # type: ignore[index]
        assert drag("legal_drag").declaration_fields["subject_key"] not in twenty_ids

    def test_the_subject_type_is_the_boards_grain_not_the_twenty_object_name(self) -> None:
        assert PATIENT_PROGRAM_BOARD.subject_type != PATIENT_PROGRAM_BOARD.object_name


class TestARecordWithoutACanonicalIdentifierIsRefused:
    """Spec: "A record without a canonical identifier is refused, not guessed"."""

    def test_a_missing_canonical_id_maps_to_unmapped(self) -> None:
        disposition = interpret(payload("missing_canonical_id"), V1_BOARD_MAPPINGS)
        assert disposition == Unmapped(
            record_ref=RecordRef("patientProgram", "twenty-record-patientprogram-0003"),
            board=PATIENT_PROGRAM_BOARD.board,
        )

    def test_an_unmapped_record_produces_no_declaration_and_no_guess(self) -> None:
        disposition = interpret(payload("missing_canonical_id"), V1_BOARD_MAPPINGS)
        assert not isinstance(disposition, Drag)
        assert not hasattr(disposition, "declaration_fields")

    def test_a_blank_canonical_id_is_refused_the_same_way_as_a_missing_one(self) -> None:
        body = payload("legal_drag")
        body["record"]["patient"]["canonicalPatientId"] = "   "  # type: ignore[index]
        assert isinstance(interpret(body, V1_BOARD_MAPPINGS), Unmapped)

    def test_the_unmapped_disposition_names_only_the_record_id_and_board(self) -> None:
        # The log line is built from this disposition, so its repr is the leak surface.
        rendered = repr(interpret(payload("missing_canonical_id"), V1_BOARD_MAPPINGS))
        for demographic in DEMOGRAPHIC_STRINGS:
            assert demographic not in rendered


class TestRedeliveryDerivesTheSameIdempotencyKey:
    """Design decision 4 / D16: the webhook event id is the logical time."""

    def test_the_redelivery_fixture_derives_an_identical_key(self) -> None:
        assert drag("redelivery_duplicate").idempotency_key == drag("legal_drag").idempotency_key

    def test_the_key_is_derived_by_pulse_core_with_the_event_id_as_logical_time(self) -> None:
        fields = drag("legal_drag").declaration_fields
        assert drag("legal_drag").idempotency_key == derive_idempotency_key(
            writer_id=WEBHOOK_WRITER_ID,
            subject_type=str(fields["subject_type"]),
            subject_key=str(fields["subject_key"]),
            command_type=DRAG_COMMAND_TYPE,
            payload={"program": "diabetes-mgmt"},
            logical_time="evt-twenty-fixture-legal-drag-0001",
        )

    def test_a_different_delivery_of_the_same_move_derives_a_different_key(self) -> None:
        body = payload("legal_drag")
        body["eventId"] = "evt-twenty-fixture-legal-drag-0002"
        second = interpret(body, V1_BOARD_MAPPINGS)
        assert isinstance(second, Drag)
        assert second.idempotency_key != drag("legal_drag").idempotency_key


class TestMalformedPayloadsAreRefusedByFieldName:
    """A payload that is structurally impossible is an error naming a field path, never a value."""

    @pytest.mark.parametrize("missing", ["eventId", "record", "workspaceMember"])
    def test_a_structurally_impossible_payload_names_the_field_path_only(self, missing: str) -> None:
        body = payload("legal_drag")
        del body[missing]
        if missing == "workspaceMember":
            # The dragging member is evidence, not a precondition — its absence is not an error.
            disposition = interpret(body, V1_BOARD_MAPPINGS)
            assert isinstance(disposition, Drag)
            assert disposition.member_ref is None
            return
        with pytest.raises(MalformedPayloadError) as raised:
            interpret(body, V1_BOARD_MAPPINGS)
        assert raised.value.field_path.startswith(missing.split(".")[0])

    def test_a_missing_as_of_time_is_refused_rather_than_stamped_with_the_wall_clock(self) -> None:
        body = payload("legal_drag")
        del body["record"]["lifecycleStatusAsOf"]  # type: ignore[union-attr]
        with pytest.raises(MalformedPayloadError) as raised:
            interpret(body, V1_BOARD_MAPPINGS)
        assert raised.value.field_path == "record.lifecycleStatusAsOf"

    def test_the_error_message_carries_no_payload_values(self) -> None:
        body = payload("legal_drag")
        del body["eventId"]
        with pytest.raises(MalformedPayloadError) as raised:
            interpret(body, V1_BOARD_MAPPINGS)
        for demographic in DEMOGRAPHIC_STRINGS:
            assert demographic not in str(raised.value)


class TestBoardMappingConfig:
    def test_the_v1_config_is_exactly_one_board(self) -> None:
        assert len(V1_BOARD_MAPPINGS) == 1

    def test_the_board_is_the_object_and_its_status_field(self) -> None:
        assert PATIENT_PROGRAM_BOARD.board == "patientProgram.lifecycleStatus"

    def test_the_as_of_field_follows_the_twenty_data_models_lww_convention(self) -> None:
        assert PATIENT_PROGRAM_BOARD.as_of_field == "lifecycleStatusAsOf"

    def test_a_second_board_maps_its_own_object_without_touching_the_first(self) -> None:
        provider_board = BoardMapping(
            object_name="provider",
            status_field="lifecycleStatus",
            subject_type="credentialing",
            canonical_key_path=("npi",),
        )
        disposition = interpret(payload("noop_unmapped_object"), (*V1_BOARD_MAPPINGS, provider_board))
        assert isinstance(disposition, Drag)
        assert disposition.declaration_fields["subject_type"] == "credentialing"
        assert disposition.declaration_fields["subject_key"] == "1999999999"
        assert disposition.declaration_fields["payload"] == {}


class TestNoPayloadContentEscapesIntoADeclaration:
    @pytest.mark.parametrize("name", ["legal_drag", "illegal_drag", "redelivery_duplicate"])
    def test_no_demographic_string_reaches_the_declaration_fields(self, name: str) -> None:
        rendered = repr(drag(name).declaration_fields)
        for demographic in DEMOGRAPHIC_STRINGS:
            assert demographic not in rendered
