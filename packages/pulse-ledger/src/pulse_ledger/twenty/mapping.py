"""Drag → command: the pure core of the Twenty kanban webhook route (design decision 1).

One function, `interpret`, turns a verified webhook body plus the service's board mappings into a
typed disposition — `Drag`, `NoOp`, or `Unmapped`. It builds no app, opens no socket, and calls no
committer, so the three decisions that are expensive to get wrong (which subject, which state,
which logical time) are pinned by tests that cost a file read.

What each disposition means, and why the boundary sits where it does:

- **`Drag`** — a record update on a mapped board whose changed fields include that board's status
  field, and whose record carries its canonical identifier. It carries the declaration's *fields*
  rather than a `Declaration`: attribution is the route's (decision 2), stamped by a constant
  `Writer`, and `Writer.attribute` refuses a body that already names an actor. Building a
  half-attributed `Declaration` here would either duplicate that rule or defeat it.
- **`NoOp`** — Twenty's CRUD noise: another object, a create or delete, an update that never
  touched the status field. Acknowledged as success so Twenty does not redeliver it forever, and
  written nowhere (`event-envelope-spec.md`'s two-vocabularies rule).
- **`Unmapped`** — a mapped drag whose record lacks the canonical identifier. Never a guess: the
  Twenty record ID is internal and is not a subject key, so there is nothing to fall back to.

**The state is the column dragged to, and legality is not decided here.** `to_state` is the status
field's `after` value verbatim; the catalog rejects an illegal move downstream, carrying its own
reason and version. A mapping that pre-filtered illegal moves would be a second, silent copy of the
catalog.

**The logical time is the delivery, not the clock** (decision 4, D16). `derive_idempotency_key`
takes Twenty's `eventId`, so an at-least-once redelivery of one notification derives one key and
commits one event, while a genuine re-drag arrives under a new delivery id and is a new command.

**PHI posture.** The body carries record fields — patient names — and nothing built here may. The
declaration's `subject_key` is the canonical spine ID, its `payload` is the program code, its
`evidence` is two opaque Twenty refs, and `MalformedPayloadError` names a *field path*, never a
value. Every exit from this module is an identifier or a fixed code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pulse_core.idempotency import derive_idempotency_key

#: The writer this route commits as (decision 2). The same string is the idempotency key's writer
#: half, so a replay is only ever recognised against this route's own keys.
WEBHOOK_WRITER_ID = "twenty-webhook"

#: A drag is a state move and nothing else; the catalog's command for that is `declare_transition`.
DRAG_COMMAND_TYPE = "declare_transition"

#: `evidence.system` for both refs — the source system, per the command-api rule that a system
#: actor carries evidence.
TWENTY_EVIDENCE_SYSTEM = "twenty"

#: The only `eventType` that can be a drag. Creates and deletes move no column.
RECORD_UPDATED_EVENT = "record.updated"

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
    to act on; this is a body that does not have the shape Twenty documents.
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

    `canonical_key_path` walks the record to the canonical spine ID — `("patient",
    "canonicalPatientId")` for the v1 board. `program_path` is optional because the envelope's
    `program` field is required for patient events only.
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

        This is the declaration's `effective_at`: when Twenty says the column changed, not when the
        webhook happened to be delivered or handled.
        """
        return f"{self.status_field}AsOf"


#: The one v1 board (decision 3): PatientProgram's `lifecycleStatus`, the patient-state grain per
#: `twenty-data-model.md`. `subject_type` is `enrollment` — the catalog's ledger-owned subject for
#: patient-in-program lifecycle, which is exactly what a PatientProgram row is.
V1_BOARD_MAPPINGS: tuple[BoardMapping, ...] = (
    BoardMapping(
        object_name="patientProgram",
        status_field="lifecycleStatus",
        subject_type="enrollment",
        canonical_key_path=("patient", "canonicalPatientId"),
        program_path=("program", "code"),
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
    """A mapped drag whose record carries no canonical identifier — refused, never guessed."""

    record_ref: RecordRef
    board: str


Disposition = Drag | NoOp | Unmapped


def interpret(payload: Mapping[str, object], mappings: Sequence[BoardMapping]) -> Disposition:
    """Interpret one verified webhook body against the configured boards.

    `mappings` is required rather than defaulted to `V1_BOARD_MAPPINGS`: which boards this service
    listens to is a deployment fact, and a default would let a caller commit against boards it
    never configured.

    Raises `MalformedPayloadError` for a body that is not the shape Twenty documents. Every
    well-formed body returns a disposition — including the ones that produce no command.
    """
    if payload.get("eventType") != RECORD_UPDATED_EVENT:
        return NoOp(NOOP_NOT_A_RECORD_UPDATE)

    object_name = _text_at(payload, ("objectMetadata", "nameSingular"))
    if object_name is None:
        raise MalformedPayloadError("objectMetadata.nameSingular")
    mapping = next((board for board in mappings if board.object_name == object_name), None)
    if mapping is None:
        return NoOp(NOOP_UNMAPPED_OBJECT)

    to_state = _dragged_to(payload, mapping.status_field)
    if to_state is None:
        return NoOp(NOOP_STATUS_FIELD_UNTOUCHED)

    record = payload.get("record")
    if not isinstance(record, Mapping):
        raise MalformedPayloadError("record")
    record_id = _text_at(record, ("id",))
    if record_id is None:
        raise MalformedPayloadError("record.id")
    card_ref = RecordRef(object_name, record_id)

    canonical_key = _text_at(record, mapping.canonical_key_path)
    if canonical_key is None:
        return Unmapped(record_ref=card_ref, board=mapping.board)
    return _drag(payload, record, mapping, card_ref=card_ref, canonical_key=canonical_key, to_state=to_state)


def _drag(
    payload: Mapping[str, object],
    record: Mapping[str, object],
    mapping: BoardMapping,
    *,
    card_ref: RecordRef,
    canonical_key: str,
    to_state: str,
) -> Drag:
    """Build the command for a drag `interpret` has already decided is mapped and resolvable.

    Split out only so each half stays readable: `interpret` decides *whether* there is a command,
    this decides *what* it is.
    """
    event_id = _text_at(payload, ("eventId",))
    if event_id is None:
        raise MalformedPayloadError("eventId")
    effective_at = _parse_timestamp(record.get(mapping.as_of_field), f"record.{mapping.as_of_field}")

    member_id = _text_at(payload, ("workspaceMember", "id"))
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
            logical_time=event_id,
        ),
        card_ref=card_ref,
        member_ref=member_ref,
    )


def _evidence(member_ref: str | None, card_ref: RecordRef) -> dict[str, object]:
    """Two opaque refs and their system — the audit trail for who dragged, with no record fields.

    The workspace member is evidence, not the actor (decision 2): the HMAC authenticates Twenty,
    and nothing in it proves which human moved the card.
    """
    evidence: dict[str, object] = {"system": TWENTY_EVIDENCE_SYSTEM}
    if member_ref is not None:
        evidence["ref"] = member_ref
    evidence["record_ref"] = str(card_ref)
    return evidence


def _dragged_to(payload: Mapping[str, object], status_field: str) -> str | None:
    """The status field's new value, or `None` if this update never touched it.

    Reads `updatedFields`, not `record[status_field]`: the record always carries a status, so
    keying on it would turn every unrelated edit into a drag back to the column it already sits in.
    """
    updated_fields = payload.get("updatedFields")
    if not isinstance(updated_fields, Sequence) or isinstance(updated_fields, (str, bytes)):
        return None
    for entry in updated_fields:
        if isinstance(entry, Mapping) and entry.get("name") == status_field:
            after = entry.get("after")
            if not isinstance(after, str) or not after.strip():
                raise MalformedPayloadError(f"updatedFields[{status_field}].after")
            return after
    return None


def _text_at(source: Mapping[str, object], path: Sequence[str]) -> str | None:
    """The non-blank string at `path`, or `None` if any step is missing, blank, or not a string.

    Blank collapses to missing deliberately: an empty `canonicalPatientId` is as much "no canonical
    identity" as an absent one, and treating them differently would make one of them a guess.
    """
    current: object = source
    for step in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(step)
    return current if isinstance(current, str) and current.strip() else None


def _parse_timestamp(value: object, field_path: str) -> datetime:
    """Twenty's ISO-8601 update time as an aware `datetime`.

    A missing or unparseable value raises rather than defaulting to now: `effective_at` is when the
    fact became true, and substituting the wall clock would silently backdate or postdate history.
    `Z` is normalised because `datetime.fromisoformat` did not accept it before Python 3.11.
    """
    if not isinstance(value, str) or not value.strip():
        raise MalformedPayloadError(field_path)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise MalformedPayloadError(field_path) from error
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise MalformedPayloadError(field_path)
    return parsed
