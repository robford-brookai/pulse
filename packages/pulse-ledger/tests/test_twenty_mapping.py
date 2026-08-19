"""Task 5.2: the pure drag → command core, against the contract Twenty v2.30 actually sends.

Every case here is one of the re-cut synthetic fixtures (shaped from the live captures in
`fixtures/twenty/captured/`) run through `interpret`. Nothing in this file builds an app, opens a
socket, or touches a committer — that is the point of the module under test being pure, and it is
what lets the retrofit-expensive decisions (which subject, which state, which logical time) be
pinned by cheap tests.

PHI posture: the fixtures carry recognizable fakes (`Canary <Case>` as the record's card title),
so the scans below can assert that no demographic string reaches a declaration, an evidence
block, or a disposition's repr.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from pulse_core.idempotency import derive_idempotency_key
from pulse_ledger.twenty.mapping import (
    DRAG_COMMAND_TYPE,
    NOOP_ECHO_OF_RECORD,
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

#: `legal_drag.json`'s record.updatedAt — the drag's effective time AND its idempotency source.
LEGAL_DRAG_UPDATED_AT = "2026-08-06T15:04:00.000Z"


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
        assert disposition.declaration_fields["to_state"] == "active"

    def test_the_target_state_is_the_new_column_not_the_old_one(self) -> None:
        # `illegal_drag` moves backwards (`active` → `pending_start`); the mapping declares the
        # column dragged *to* and leaves legality to the catalog.
        assert drag("illegal_drag").declaration_fields["to_state"] == "pending_start"

    def test_the_wire_state_is_decoded_to_catalog_vocabulary(self) -> None:
        # The wire carries Twenty's storage encoding (`ACTIVE`, UPPER_SNAKE per
        # `encode_option_value`); the declaration carries the catalog's own state name.
        body = payload("legal_drag")
        assert body["record"]["lifecycleStatus"] == "ACTIVE"  # type: ignore[index]
        assert drag("legal_drag").declaration_fields["to_state"] == "active"

    def test_a_wire_state_no_catalog_state_encodes_to_passes_through_verbatim(self) -> None:
        # Vocabulary membership is the catalog's verdict: the mapping neither guesses a decode
        # nor pre-filters, so the catalog downstream refuses it with its own reason and version.
        body = payload("legal_drag")
        body["record"]["lifecycleStatus"] = "NOT_A_CATALOG_STATE"  # type: ignore[index]
        disposition = interpret(body, V1_BOARD_MAPPINGS)
        assert isinstance(disposition, Drag)
        assert disposition.declaration_fields["to_state"] == "NOT_A_CATALOG_STATE"

    def test_the_card_and_member_refs_name_the_twenty_records(self) -> None:
        disposition = drag("legal_drag")
        assert disposition.card_ref == RecordRef("patientProgram", "twenty-record-patientprogram-0001")
        assert disposition.member_ref == "workspaceMember:wsm-0001-canary-nurse"

    def test_an_api_sourced_write_carries_no_member_ref(self) -> None:
        # Observed live: `updatedBy.workspaceMemberId` is null when the write came through the
        # REST API rather than a human in the UI.
        body = payload("legal_drag")
        body["record"]["updatedBy"] = {  # type: ignore[index]
            "source": "API",
            "workspaceMemberId": None,
            "name": "pulse-dev",
            "context": {},
        }
        disposition = interpret(body, V1_BOARD_MAPPINGS)
        assert isinstance(disposition, Drag)
        assert disposition.member_ref is None

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
        assert drag("legal_drag").declaration_fields["payload"] == {"program": "rpm"}


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

    def test_the_gate_is_the_event_names_updated_suffix(self) -> None:
        # `eventName` is object-qualified (`patientProgram.created`), so the action gate is its
        # suffix — never a bare `eventType` field, which Twenty does not send.
        for name in ("noop_create", "noop_delete"):
            event_name = payload(name)["eventName"]
            assert isinstance(event_name, str)
            assert not event_name.endswith(".updated")

    def test_a_missing_event_name_is_noise_not_an_error(self) -> None:
        body = payload("legal_drag")
        del body["eventName"]
        assert interpret(body, V1_BOARD_MAPPINGS) == NoOp(NOOP_NOT_A_RECORD_UPDATE)

    def test_a_noop_reason_is_a_fixed_code_carrying_no_payload_content(self) -> None:
        for name in ("noop_create", "noop_delete", "noop_non_status_update", "noop_unmapped_object"):
            reason = interpret(payload(name), V1_BOARD_MAPPINGS).reason  # type: ignore[union-attr]
            assert reason in {NOOP_NOT_A_RECORD_UPDATE, NOOP_STATUS_FIELD_UNTOUCHED, NOOP_UNMAPPED_OBJECT}

    def test_no_mappings_at_all_makes_every_object_unmapped(self) -> None:
        assert interpret(payload("legal_drag"), ()) == NoOp(NOOP_UNMAPPED_OBJECT)


def record_says(state: str | None) -> Callable[[str, str], str | None]:
    """A state-of-record reader that answers `state` for every subject."""

    def state_of_record(subject_type: str, subject_key: str) -> str | None:
        return state

    return state_of_record


class TestAnEchoOfTheStateOfRecordIsANoop:
    """Spec: "An echo of the state of record is a noop" — the projection loop's terminator.

    A heal-back or projection write fires the same `.updated` webhook back at this route, and
    `updatedBy` cannot tell those writes from a user's (Twenty collapses API-sourced writes to a
    null `workspaceMemberId`), so state equality against the state of record is the discriminator
    (design decision 5). `legal_drag`'s wire state is `ACTIVE`, so a reader answering `active`
    makes it an echo and any other answer keeps it a genuine drag.
    """

    def test_a_drag_to_the_state_of_record_is_a_noop_with_the_echo_reason(self) -> None:
        disposition = interpret(payload("legal_drag"), V1_BOARD_MAPPINGS, state_of_record=record_says("active"))
        assert disposition == NoOp(NOOP_ECHO_OF_RECORD)

    def test_the_comparison_is_encoded_not_a_raw_string_match(self) -> None:
        # The reader answers in catalog vocabulary (`active`); the wire carries Twenty's storage
        # encoding (`ACTIVE`). The suppression only fires if the mapping compares through
        # `encode_option_value` — a raw equality of the two strings never would.
        record = payload("legal_drag")["record"]
        assert isinstance(record, dict)
        assert record["lifecycleStatus"] == "ACTIVE"
        disposition = interpret(payload("legal_drag"), V1_BOARD_MAPPINGS, state_of_record=record_says("active"))
        assert disposition == NoOp(NOOP_ECHO_OF_RECORD)

    def test_a_genuine_drag_to_a_different_state_still_maps_to_exactly_one_command(self) -> None:
        # Regression pin for "A status-field update on a mapped board yields one command": echo
        # suppression must not swallow a real move.
        disposition = interpret(payload("legal_drag"), V1_BOARD_MAPPINGS, state_of_record=record_says("on_hold"))
        assert isinstance(disposition, Drag)
        assert disposition.declaration_fields["to_state"] == "active"

    def test_the_reader_is_asked_for_the_mapped_subject(self) -> None:
        asked: list[tuple[str, str]] = []

        def reader(subject_type: str, subject_key: str) -> str | None:
            asked.append((subject_type, subject_key))
            return "active"

        interpret(payload("legal_drag"), V1_BOARD_MAPPINGS, state_of_record=reader)
        assert asked == [("enrollment", "DIM_PATIENT_CONFORMED-000101")]

    def test_a_subject_the_ledger_has_never_seen_is_not_an_echo(self) -> None:
        disposition = interpret(payload("legal_drag"), V1_BOARD_MAPPINGS, state_of_record=record_says(None))
        assert isinstance(disposition, Drag)

    def test_no_reader_at_all_leaves_the_mapping_unchanged(self) -> None:
        # An app built without a state reader degrades to the pre-suppression behavior: the drag
        # maps, and the catalog refuses the self-transition downstream.
        assert isinstance(interpret(payload("legal_drag"), V1_BOARD_MAPPINGS), Drag)

    def test_an_echo_needs_no_establishable_effective_time(self) -> None:
        # The suppression sits before the timestamp refusal: a suppressed drag builds no command,
        # so it has no time to establish — `Unmapped` here would be noise.
        body = payload("legal_drag")
        assert isinstance(body["record"], dict)
        del body["record"]["updatedAt"]
        disposition = interpret(body, V1_BOARD_MAPPINGS, state_of_record=record_says("active"))
        assert disposition == NoOp(NOOP_ECHO_OF_RECORD)


class TestUpdatedFieldsIsANameList:
    """Spec: `updatedFields` is a list of field *names*; values come off the flat `record`."""

    def test_the_new_value_is_read_from_the_flat_record(self) -> None:
        body = payload("legal_drag")
        assert body["updatedFields"] == ["lifecycleStatus"]
        assert drag("legal_drag").declaration_fields["to_state"] == "active"

    def test_an_update_not_naming_the_status_field_is_untouched(self) -> None:
        assert interpret(payload("noop_non_status_update"), V1_BOARD_MAPPINGS) == NoOp(NOOP_STATUS_FIELD_UNTOUCHED)

    def test_a_named_status_field_missing_from_the_record_is_malformed(self) -> None:
        body = payload("legal_drag")
        del body["record"]["lifecycleStatus"]  # type: ignore[union-attr]
        with pytest.raises(MalformedPayloadError) as raised:
            interpret(body, V1_BOARD_MAPPINGS)
        assert raised.value.field_path == "record.lifecycleStatus"

    def test_an_updated_event_without_updated_fields_is_malformed(self) -> None:
        body = payload("legal_drag")
        del body["updatedFields"]
        with pytest.raises(MalformedPayloadError) as raised:
            interpret(body, V1_BOARD_MAPPINGS)
        assert raised.value.field_path == "updatedFields"


class TestTheCanonicalIdentifierResolvesTheSubject:
    """Spec: "The canonical identifier resolves the subject"."""

    def test_subject_type_and_key_come_from_the_mapping_and_the_canonical_id(self) -> None:
        fields = drag("legal_drag").declaration_fields
        assert fields["subject_type"] == PATIENT_PROGRAM_BOARD.subject_type
        assert fields["subject_key"] == "DIM_PATIENT_CONFORMED-000101"

    def test_the_canonical_id_is_a_flat_scalar_on_the_record(self) -> None:
        # The webhook record is the flat ORM entity: the denormalized `canonicalPatientId` and
        # `programCode` columns exist so resolution never traverses a nested object or calls back.
        assert PATIENT_PROGRAM_BOARD.canonical_key_path == ("canonicalPatientId",)
        assert PATIENT_PROGRAM_BOARD.program_path == ("programCode",)

    def test_no_twenty_record_id_is_ever_a_subject_key(self) -> None:
        record = payload("legal_drag")["record"]
        assert isinstance(record, dict)
        twenty_ids = {record["id"], record["patientId"], record["programId"]}
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
        body["record"]["canonicalPatientId"] = "   "  # type: ignore[index]
        assert isinstance(interpret(body, V1_BOARD_MAPPINGS), Unmapped)

    def test_the_unmapped_disposition_names_only_the_record_id_and_board(self) -> None:
        # The log line is built from this disposition, so its repr is the leak surface.
        rendered = repr(interpret(payload("missing_canonical_id"), V1_BOARD_MAPPINGS))
        for demographic in DEMOGRAPHIC_STRINGS:
            assert demographic not in rendered


class TestEffectiveTimeComesFromTheRecord:
    """Spec: "Effective time comes from the record, never the wall clock" (F3, settled live)."""

    def test_effective_at_is_the_records_update_stamp(self) -> None:
        assert drag("legal_drag").declaration_fields["effective_at"] == datetime(2026, 8, 6, 15, 4, tzinfo=timezone.utc)

    def test_a_stale_as_of_field_is_never_inherited(self) -> None:
        # Observed in both captured drags: `lifecycleStatusAsOf` did NOT move while the status
        # changed. Inheriting it would silently backdate the event to the previous projection.
        body = payload("legal_drag")
        as_of = body["record"]["lifecycleStatusAsOf"]  # type: ignore[index]
        disposition = interpret(body, V1_BOARD_MAPPINGS)
        assert isinstance(disposition, Drag)
        effective_at = disposition.declaration_fields["effective_at"]
        assert isinstance(effective_at, datetime)
        assert effective_at != datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))

    @pytest.mark.parametrize("break_it", ["delete", "blank", "unparseable", "naive"])
    def test_a_record_with_no_establishable_effective_time_is_refused(self, break_it: str) -> None:
        # Refused as *unmapped*, not committed with an inherited or wall-clock guess and not a
        # malformed-body error: the body parses fine, it just cannot be committed honestly.
        body = payload("legal_drag")
        record = body["record"]
        assert isinstance(record, dict)
        if break_it == "delete":
            del record["updatedAt"]
        elif break_it == "blank":
            record["updatedAt"] = "   "
        elif break_it == "unparseable":
            record["updatedAt"] = "not-a-timestamp"
        else:
            record["updatedAt"] = "2026-08-06T15:04:00"  # no zone: a time nobody can place
        disposition = interpret(body, V1_BOARD_MAPPINGS)
        assert disposition == Unmapped(
            record_ref=RecordRef("patientProgram", "twenty-record-patientprogram-0001"),
            board=PATIENT_PROGRAM_BOARD.board,
        )


class TestRecordUpdatedAtIsTheIdempotencySource:
    """Design decision 4 / D16: no per-delivery event id exists, so `record.updatedAt` is the
    logical time — stable across redeliveries of one write, distinct for a genuine re-drag."""

    def test_the_redelivery_fixture_derives_an_identical_key(self) -> None:
        assert drag("redelivery_duplicate").idempotency_key == drag("legal_drag").idempotency_key

    def test_the_key_is_derived_by_pulse_core_with_updated_at_as_logical_time(self) -> None:
        fields = drag("legal_drag").declaration_fields
        assert drag("legal_drag").idempotency_key == derive_idempotency_key(
            writer_id=WEBHOOK_WRITER_ID,
            subject_type=str(fields["subject_type"]),
            subject_key=str(fields["subject_key"]),
            command_type=DRAG_COMMAND_TYPE,
            payload={"program": "rpm"},
            logical_time=LEGAL_DRAG_UPDATED_AT,
        )

    def test_a_genuine_second_drag_is_not_mistaken_for_a_replay(self) -> None:
        # Observed live (D16): two real drags on one record produced distinct `record.updatedAt`
        # values, so a later stamp is a new command, never a replay.
        body = payload("legal_drag")
        body["record"]["updatedAt"] = "2026-08-06T15:09:12.371Z"  # type: ignore[index]
        second = interpret(body, V1_BOARD_MAPPINGS)
        assert isinstance(second, Drag)
        assert second.idempotency_key != drag("legal_drag").idempotency_key


class TestMalformedPayloadsAreRefusedByFieldName:
    """A payload that is structurally impossible is an error naming a field path, never a value."""

    @pytest.mark.parametrize("missing", ["record", "objectMetadata"])
    def test_a_structurally_impossible_payload_names_the_field_path_only(self, missing: str) -> None:
        body = payload("legal_drag")
        del body[missing]
        with pytest.raises(MalformedPayloadError) as raised:
            interpret(body, V1_BOARD_MAPPINGS)
        assert raised.value.field_path.startswith(missing.split(".")[0])

    def test_a_missing_updated_by_is_not_an_error(self) -> None:
        # The dragging member is evidence, not a precondition — its absence is not an error.
        body = payload("legal_drag")
        del body["record"]["updatedBy"]  # type: ignore[union-attr]
        disposition = interpret(body, V1_BOARD_MAPPINGS)
        assert isinstance(disposition, Drag)
        assert disposition.member_ref is None

    def test_the_error_message_carries_no_payload_values(self) -> None:
        body = payload("legal_drag")
        del body["record"]
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
        # `credentialing` is not a catalog subject, so the wire value passes through undecoded
        # for whatever validates that board downstream.
        assert disposition.declaration_fields["to_state"] == "CREDENTIALED"


class TestNoPayloadContentEscapesIntoADeclaration:
    @pytest.mark.parametrize("name", ["legal_drag", "illegal_drag", "redelivery_duplicate"])
    def test_no_demographic_string_reaches_the_declaration_fields(self, name: str) -> None:
        rendered = repr(drag(name).declaration_fields)
        for demographic in DEMOGRAPHIC_STRINGS:
            assert demographic not in rendered
