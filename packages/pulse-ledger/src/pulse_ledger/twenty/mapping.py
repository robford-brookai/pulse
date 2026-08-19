"""Drag → command: the pure core of the Twenty kanban webhook route (design decision 1).

One function, `interpret`, turns a verified webhook body plus the service's board mappings into a
typed disposition — `Drag`, `NoOp`, or `Unmapped`. It builds no app, opens no socket, and calls no
committer, so the three decisions that are expensive to get wrong (which subject, which state,
which logical time) are pinned by tests that cost a file read.

The payload shape here is the one Twenty v2.30 actually sends, captured live in
`tests/fixtures/twenty/captured/` (task 4.2): the event discriminator is `eventName`
(`patientProgram.updated`), `updatedFields` is a string array of field *names* whose new values
sit on the flat `record`, the dragging member is `record.updatedBy.workspaceMemberId` (null for
an API-sourced write), and there is no per-delivery event id.

What each disposition means, and why the boundary sits where it does:

- **`Drag`** — a record update on a mapped board whose changed fields include that board's status
  field, and whose record carries its canonical identifier. It carries the declaration's *fields*
  rather than a `Declaration`: attribution is the route's (decision 2), stamped by a constant
  `Writer`, and `Writer.attribute` refuses a body that already names an actor. Building a
  half-attributed `Declaration` here would either duplicate that rule or defeat it.
- **`NoOp`** — Twenty's CRUD noise: another object, a create or delete, an update that never
  touched the status field. Acknowledged as success so Twenty does not redeliver it forever, and
  written nowhere (`event-envelope-spec.md`'s two-vocabularies rule).
- **`Unmapped`** — a mapped drag this route refuses rather than guesses about: the record lacks
  its canonical identifier, or carries no timestamp its effective time can be established from.
  The Twenty record ID is internal and is not a subject key, and an inherited or wall-clock
  `effective_at` would be a silently wrong event rather than a failure — so both are refused.

**The state is the column dragged to, and legality is not decided here.** The wire carries the
SELECT value in Twenty's storage encoding (`ACTIVE` — see
`pulse_core.twenty_validate.encode_option_value`); `_decode_wire_state` inverts that encoding
against the catalog's own states so `to_state` is catalog vocabulary, and a wire value no catalog
state encodes to passes through verbatim for the catalog to refuse downstream with its own reason
and version. A mapping that pre-filtered illegal or unknown moves would be a second, silent copy
of the catalog.

**The logical time is the record's update stamp, not the clock and not a delivery id** (decision
4, D16, F3 — settled by the 4.2 capture). Twenty sends no per-delivery event id, and a UI drag
stamps no as-of field (`lifecycleStatusAsOf` was observed stale across two live drags), so
`record.updatedAt` is both the idempotency key's logical time and the drag's `effective_at`: a
redelivery of one write carries the same `updatedAt` and replays, a genuine re-drag advances it
and is a new command. A record with no establishable `updatedAt` is refused as `Unmapped` —
inheriting the previous projection's time would commit a well-formed event carrying a wrong time,
which is worse than failing.

**PHI posture.** The body carries record fields — card titles, member names — and nothing built
here may. The declaration's `subject_key` is the canonical spine ID, its `payload` is the program
code, its `evidence` is two opaque Twenty refs, and `MalformedPayloadError` names a *field path*,
never a value. Every exit from this module is an identifier or a fixed code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pulse_core.generated import TRANSITIONS
from pulse_core.idempotency import derive_idempotency_key
from pulse_core.twenty_validate import encode_option_value

#: The writer this route commits as (decision 2). The same string is the idempotency key's writer
#: half, so a replay is only ever recognised against this route's own keys.
WEBHOOK_WRITER_ID = "twenty-webhook"

#: A drag is a state move and nothing else; the catalog's command for that is `declare_transition`.
DRAG_COMMAND_TYPE = "declare_transition"

#: `evidence.system` for both refs — the source system, per the command-api rule that a system
#: actor carries evidence.
TWENTY_EVIDENCE_SYSTEM = "twenty"

#: Only an `.updated` event can be a drag. Twenty's discriminator is `eventName`, an
#: object-qualified `{objectName}.{action}` string (`patientProgram.updated`) — creates and
#: deletes move no column.
UPDATED_EVENT_SUFFIX = ".updated"

#: `NoOp.reason` values. Fixed codes, not sentences built from the payload: they reach a structured
#: log line and a response body, and a reason interpolating record content would leak there.
NOOP_NOT_A_RECORD_UPDATE = "not_a_record_update"
NOOP_UNMAPPED_OBJECT = "unmapped_object"
NOOP_STATUS_FIELD_UNTOUCHED = "status_field_untouched"


class TwentyPayloadError(ValueError):
    """A webhook body this module cannot interpret at all."""


class MalformedPayloadError(TwentyPayloadError):
    """A structurally impossible payload, named by field path.

    Carries `field_path` and nothing else. The path is made of Twenty's *field names*, which are
    schema, so this message is safe in a log line — the values at those paths are not, and never
    appear here. Distinct from `NoOp`/`Unmapped`, which are well-formed bodies this route declines
    to act on; this is a body that does not have the shape Twenty sends.
    """

    def __init__(self, field_path: str) -> None:
        self.field_path = field_path
        super().__init__(f"twenty webhook payload is missing or malformed at {field_path!r}")


@dataclass(frozen=True)
class RecordRef:
    """One Twenty record, by object and internal id — a card reference, never a subject key."""

    object_name: str
    record_id: str

    def __str__(self) -> str:
        return f"{self.object_name}:{self.record_id}"


@dataclass(frozen=True)
class BoardMapping:
    """One kanban board: a status field on a Twenty object, and the subject it projects.

    Static service configuration (decision 3), passed in beside `TwentyWebhookConfig`. The catalog
    knows subjects and transitions but not which Twenty object and field project them, so this
    wiring cannot be derived from it and is stated once, here.

    `canonical_key_path` walks the record to the canonical spine ID. The webhook `record` is the
    flat ORM entity, so for the v1 board this is the denormalized `("canonicalPatientId",)` —
    subject resolution reads the delivered payload only, never a read-back call. `program_path` is
    optional because the envelope's `program` field is required for patient events only.
    """

    object_name: str
    status_field: str
    subject_type: str
    canonical_key_path: tuple[str, ...]
    program_path: tuple[str, ...] | None = None

    @property
    def board(self) -> str:
        """The board's name in logs and dispositions — the object and the field that is its columns."""
        return f"{self.object_name}.{self.status_field}"

    @property
    def as_of_field(self) -> str:
        """The status field's LWW guard, per `twenty-data-model.md`'s `<dimension>StatusAsOf` pair.

        Named here for the projection writers that stamp it. A UI drag does *not* stamp it (F3,
        observed live in the 4.2 capture: `lifecycleStatusAsOf` stayed put while the status
        changed), so a drag's `effective_at` never reads this field — it derives from
        `record.updatedAt` instead, and reading a stale as-of here would inherit the previous
        projection's time.
        """
        return f"{self.status_field}AsOf"


#: The one v1 board (decision 3): PatientProgram's `lifecycleStatus`, the patient-state grain per
#: `twenty-data-model.md`. `subject_type` is `enrollment` — the catalog's ledger-owned subject for
#: patient-in-program lifecycle, which is exactly what a PatientProgram row is. The canonical and
#: program paths are the flat denormalized columns the webhook record carries directly.
V1_BOARD_MAPPINGS: tuple[BoardMapping, ...] = (
    BoardMapping(
        object_name="patientProgram",
        status_field="lifecycleStatus",
        subject_type="enrollment",
        canonical_key_path=("canonicalPatientId",),
        program_path=("programCode",),
    ),
)


@dataclass(frozen=True)
class Drag:
    """A mapped, subject-resolved drag: one command, ready for attribution and commit.

    `declaration_fields` is a `Declaration` body minus the credential-derived fields, so the route
    can hand it straight to `Writer.attribute`. `card_ref` and `member_ref` are what the feedback
    leg needs — where to comment, and who to name in evidence.
    """

    declaration_fields: Mapping[str, object]
    idempotency_key: str
    card_ref: RecordRef
    member_ref: str | None


@dataclass(frozen=True)
class NoOp:
    """Twenty CRUD noise: acknowledged as success, written nowhere."""

    reason: str


@dataclass(frozen=True)
class Unmapped:
    """A mapped drag refused rather than guessed about — no canonical identifier, or no
    establishable effective time. Either way: no command, success to Twenty, one log line naming
    the record and board only."""

    record_ref: RecordRef
    board: str


Disposition = Drag | NoOp | Unmapped


def interpret(payload: Mapping[str, object], mappings: Sequence[BoardMapping]) -> Disposition:
    """Interpret one verified webhook body against the configured boards.

    `mappings` is required rather than defaulted to `V1_BOARD_MAPPINGS`: which boards this service
    listens to is a deployment fact, and a default would let a caller commit against boards it
    never configured.

    Raises `MalformedPayloadError` for a body that is not the shape Twenty sends. Every
    well-formed body returns a disposition — including the ones that produce no command.
    """
    event_name = payload.get("eventName")
    if not isinstance(event_name, str) or not event_name.endswith(UPDATED_EVENT_SUFFIX):
        return NoOp(NOOP_NOT_A_RECORD_UPDATE)

    object_name = _text_at(payload, ("objectMetadata", "nameSingular"))
    if object_name is None:
        raise MalformedPayloadError("objectMetadata.nameSingular")
    mapping = next((board for board in mappings if board.object_name == object_name), None)
    if mapping is None:
        return NoOp(NOOP_UNMAPPED_OBJECT)

    record = payload.get("record")
    if not isinstance(record, Mapping):
        raise MalformedPayloadError("record")
    record_id = _text_at(record, ("id",))
    if record_id is None:
        raise MalformedPayloadError("record.id")
    card_ref = RecordRef(object_name, record_id)

    wire_state = _dragged_to(payload, record, mapping.status_field)
    if wire_state is None:
        return NoOp(NOOP_STATUS_FIELD_UNTOUCHED)

    canonical_key = _text_at(record, mapping.canonical_key_path)
    if canonical_key is None:
        return Unmapped(record_ref=card_ref, board=mapping.board)

    # F3: the drag's own timestamp, or a refusal. `record.updatedAt` is the only stamp a UI drag
    # writes; a record without one has no establishable effective time, and committing with an
    # inherited or wall-clock time would be silently wrong rather than visibly refused.
    updated_at_raw = _text_at(record, ("updatedAt",))
    if updated_at_raw is None:
        return Unmapped(record_ref=card_ref, board=mapping.board)
    effective_at = _parse_timestamp(updated_at_raw)
    if effective_at is None:
        return Unmapped(record_ref=card_ref, board=mapping.board)

    return _drag(
        record,
        mapping,
        card_ref=card_ref,
        canonical_key=canonical_key,
        to_state=_decode_wire_state(wire_state, mapping.subject_type),
        effective_at=effective_at,
        logical_time=updated_at_raw,
    )


def _drag(
    record: Mapping[str, object],
    mapping: BoardMapping,
    *,
    card_ref: RecordRef,
    canonical_key: str,
    to_state: str,
    effective_at: datetime,
    logical_time: str,
) -> Drag:
    """Build the command for a drag `interpret` has already decided is mapped and resolvable.

    Split out only so each half stays readable: `interpret` decides *whether* there is a command,
    this decides *what* it is.
    """
    member_id = _text_at(record, ("updatedBy", "workspaceMemberId"))
    member_ref = None if member_id is None else f"workspaceMember:{member_id}"

    command_payload: dict[str, object] = {}
    if mapping.program_path is not None:
        program = _text_at(record, mapping.program_path)
        if program is None:
            raise MalformedPayloadError("record." + ".".join(mapping.program_path))
        command_payload["program"] = program

    declaration_fields: dict[str, object] = {
        "subject_type": mapping.subject_type,
        "subject_key": canonical_key,
        "event_type": DRAG_COMMAND_TYPE,
        "to_state": to_state,
        "effective_at": effective_at,
        "evidence": _evidence(member_ref, card_ref),
        "payload": command_payload,
    }
    return Drag(
        declaration_fields=declaration_fields,
        idempotency_key=derive_idempotency_key(
            writer_id=WEBHOOK_WRITER_ID,
            subject_type=mapping.subject_type,
            subject_key=canonical_key,
            command_type=DRAG_COMMAND_TYPE,
            payload=command_payload,
            logical_time=logical_time,
        ),
        card_ref=card_ref,
        member_ref=member_ref,
    )


def _evidence(member_ref: str | None, card_ref: RecordRef) -> dict[str, object]:
    """Two opaque refs and their system — the audit trail for who dragged, with no record fields.

    The workspace member is evidence, not the actor (decision 2): the HMAC authenticates Twenty,
    and nothing in it proves which human moved the card. An API-sourced write carries a null
    `workspaceMemberId`, so the member ref is simply absent there.
    """
    evidence: dict[str, object] = {"system": TWENTY_EVIDENCE_SYSTEM}
    if member_ref is not None:
        evidence["ref"] = member_ref
    evidence["record_ref"] = str(card_ref)
    return evidence


def _dragged_to(payload: Mapping[str, object], record: Mapping[str, object], status_field: str) -> str | None:
    """The status field's new wire value, or `None` if this update never touched it.

    `updatedFields` is Twenty's list of changed field *names* — there is no per-field
    before/after pair, so the new value is read from the flat `record`. Keying on the record
    alone would turn every unrelated edit into a drag back to the column the card already sits
    in, which is why the name list gates the read.
    """
    updated_fields = payload.get("updatedFields")
    if not isinstance(updated_fields, Sequence) or isinstance(updated_fields, (str, bytes)):
        raise MalformedPayloadError("updatedFields")
    if status_field not in {entry for entry in updated_fields if isinstance(entry, str)}:
        return None
    value = record.get(status_field)
    if not isinstance(value, str) or not value.strip():
        raise MalformedPayloadError(f"record.{status_field}")
    return value.strip()


def _decode_wire_state(wire_value: str, subject_type: str) -> str:
    """The catalog state behind one wire SELECT value, by inverting the storage encoding.

    Twenty stores SELECT option values UPPER_SNAKE (`twenty_validate.encode_option_value`, proven
    bijective per field by `check_option_encoding` at deploy time), so the inverse is a lookup
    over the subject's own catalog states, not a string transform — `lower()` alone cannot know
    whether `ON_HOLD` came from `on_hold` or `on.hold`. A wire value no catalog state encodes to,
    or a subject the catalog does not know, passes through verbatim: vocabulary membership is the
    catalog's verdict to issue downstream, with its own reason and version.
    """
    adjacency = TRANSITIONS.get(subject_type)
    if adjacency is None:
        return wire_value
    for state in adjacency:
        if encode_option_value(state) == wire_value:
            return state
    return wire_value


def _text_at(source: object, path: Sequence[str]) -> str | None:
    """The non-blank string at `path`, or `None` if any step is missing, blank, or not a string.

    Blank collapses to missing deliberately: an empty `canonicalPatientId` is as much "no canonical
    identity" as an absent one, and treating them differently would make one of them a guess. The
    same collapse makes a null `updatedBy.workspaceMemberId` — Twenty's shape for an API-sourced
    write — read as "no member" rather than an error.
    """
    current: object = source
    for step in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(step)
    return current if isinstance(current, str) and current.strip() else None


def _parse_timestamp(value: str) -> datetime | None:
    """Twenty's ISO-8601 stamp as an aware `datetime`, or `None` if it does not parse as one.

    Returns `None` rather than raising: the caller's verdict for a drag with no establishable
    effective time is a *refusal* (`Unmapped`), not a malformed-body error — the body parses fine,
    it just cannot be committed without guessing a time. Naive datetimes are refused the same way:
    a timestamp with no zone is a time nobody can place. `Z` is normalised because
    `datetime.fromisoformat` did not accept it before Python 3.11.
    """
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed
