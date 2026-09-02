"""The projection's write path: one committed enrollment event onto one Twenty board record.

`apply_event` is the whole correctness story of the projection (twenty-projection design
decisions 2 and 3): resolve the subject through the denormalized `canonicalPatientId` /
`programCode` columns — canonical identifiers, never guessed — guard monotonically on the
ledger sequence against the record's `projectionSeq` watermark, and write the *full* board
state (encoded status, as-of from the event's effective time, watermark) in one PATCH, so any
out-of-band drift converges on the subject's next event.

`projected_fields` is the one place the projection decides what a record looks like after an
event. `apply_event` writes it incrementally; `twenty_projection.rebuild` folds it over a
subject's committed history (task 2.3). Neither owns a second copy, so a rebuild cannot agree
with the live write path by coincidence.

Scope boundary (task 2.1): unresolvable subjects and failed writes raise typed errors here and
nothing more — parking, retries, and the counted metrics land in task 2.2. What is already
binding is the payload posture: no error message or log line built here ever carries an event
payload value or anything read from a response body; identifiers, states of the *envelope's
own structure*, and sequences only.

The REST conventions are the pinned core surface (`docs/contracts/consumes.md`, live-verified
v2.30.0): `filter=<field>[eq]:<value>` comma-joined AND with no quoting (reserved characters
are refused, never escaped), records listed under `data.<plural>`, SELECT values stored
UPPER_SNAKE-encoded via `pulse_core.twenty_model.encode_option_value`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import httpx
from pulse_core.connector import is_watermark_stale
from pulse_core.twenty_model import encode_option_value

logger = logging.getLogger(__name__)

REST_ROOT = "/rest"

DEFAULT_TIMEOUT_SECONDS = 10.0

#: Records per page when listing a whole object. The board is one row per patient-program, so a
#: rebuild of a live scope is a handful of pages, not a scan.
DEFAULT_LIST_PAGE_SIZE = 200

#: Characters Twenty's filter grammar reserves; a value carrying one is refused rather than
#: escaped, because the grammar has no quoting and a comma silently becomes a second predicate.
FILTER_RESERVED = frozenset(",:[]()")


class ProjectionApplyError(Exception):
    """Base for every typed failure the apply core raises. Never carries payload content."""


class MalformedEventError(ProjectionApplyError):
    """The envelope is not the shape the relay publishes — names the field path only."""

    def __init__(self, field_path: str) -> None:
        self.field_path = field_path
        super().__init__(f"ledger envelope is missing or malformed at {field_path!r}")


class SubjectResolutionError(ProjectionApplyError):
    """Subject resolution failed — carries the pseudonymous subject identifiers only."""

    def __init__(self, message: str, *, subject_key: str, program: str) -> None:
        self.subject_key = subject_key
        self.program = program
        super().__init__(message)


class SubjectUnresolvedError(SubjectResolutionError):
    """No board record matches the subject. Task 2.2 turns this into a parked, counted orphan."""

    def __init__(self, *, subject_key: str, program: str) -> None:
        super().__init__(
            f"no board record for subject {subject_key!r} program {program!r}",
            subject_key=subject_key,
            program=program,
        )


class AmbiguousSubjectError(SubjectResolutionError):
    """More than one record matches — the denormalized key columns are not unique, a data fault
    that must surface rather than pick a winner."""

    def __init__(self, *, subject_key: str, program: str, count: int) -> None:
        self.count = count
        super().__init__(
            f"{count} board records match subject {subject_key!r} program {program!r}",
            subject_key=subject_key,
            program=program,
        )


class SubjectLookupError(ProjectionApplyError):
    """The resolution read failed at the transport — status code only, the body is never read.

    `status_code` is `None` for a transport-level failure (timeout, refused connection).
    """

    def __init__(self, *, status_code: int | None, detail: str | None = None) -> None:
        self.status_code = status_code
        if detail is None:
            detail = f"HTTP {status_code}" if status_code is not None else "transport error"
        super().__init__(f"board record lookup failed: {detail}")


class ProjectionWriteError(ProjectionApplyError):
    """The board write failed — record ref and status only, never anything from the body.

    Task 2.2 wraps this in the retry-then-surface posture; the type itself already guarantees
    a failure response body can never reach a log line through the error message.
    """

    def __init__(self, record_ref: str, *, status_code: int | None) -> None:
        self.record_ref = record_ref
        self.status_code = status_code
        detail = f"HTTP {status_code}" if status_code is not None else "transport error"
        super().__init__(f"board write to {record_ref!r} failed: {detail}")


@dataclass(frozen=True)
class BoardTarget:
    """One projected board: the Twenty object, its status/as-of/watermark columns, and the
    ledger subject it renders. Static wiring, same posture as `BoardMapping` on the drag side."""

    object_name: str
    plural: str
    subject_type: str
    status_field: str
    watermark_field: str

    @property
    def as_of_field(self) -> str:
        return f"{self.status_field}AsOf"


#: The one v1 board: patientProgram's `lifecycleStatus` renders the `enrollment` subject.
V1_BOARD = BoardTarget(
    object_name="patientProgram",
    plural="patientPrograms",
    subject_type="enrollment",
    status_field="lifecycleStatus",
    watermark_field="projectionSeq",
)


@dataclass(frozen=True)
class Applied:
    """One event written: the record it landed on and the sequence now watermarked there."""

    record_ref: str
    subject_key: str
    program: str
    seq: int


@dataclass(frozen=True)
class SkippedStale:
    """A logged no-op: the event's sequence is at or below the record's watermark."""

    record_ref: str
    subject_key: str
    program: str
    seq: int
    watermark: int


ApplyResult = Applied | SkippedStale


class ProjectionRestClient:
    """The projection's two verbs against one Twenty instance: a filtered listing and a PATCH.

    `transport` is the seam tests use (`httpx.MockTransport`) to fake the HTTP boundary without
    a live network — the same convention as `pulse_core.client.PulseCoreClient`. No retries
    here: task 2.2 owns the retry-then-surface posture around the apply core. Response bodies
    from failures are never read, so nothing from them can reach an error message or a log.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def __enter__(self) -> ProjectionRestClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def find_records(self, plural: str, filters: Mapping[str, str]) -> tuple[Mapping[str, object], ...]:
        """The records matching an exact-equality filter, capped at two.

        `limit=2` rather than 1: one extra row is what proves a match unambiguous, the same
        pin as the live `CoreApiClient`. Filters are sorted by field so the same lookup
        produces the same URL twice.
        """
        query = ",".join(f"{field}[eq]:{value}" for field, value in sorted(filters.items()))
        try:
            response = self._http.get(f"{REST_ROOT}/{plural}", params={"filter": query, "limit": 2})
        except httpx.TransportError as error:
            raise SubjectLookupError(status_code=None) from error
        if not response.is_success:
            raise SubjectLookupError(status_code=response.status_code)
        return _records_of(response, plural)[0]

    def list_records(
        self,
        plural: str,
        *,
        filters: Mapping[str, str] | None = None,
        page_size: int = DEFAULT_LIST_PAGE_SIZE,
    ) -> tuple[Mapping[str, object], ...]:
        """Every record of one object, optionally filtered, paged to exhaustion.

        `find_records` answers "which record is this subject's" and caps at two on purpose. This
        answers "which rows does this scope hold", which a rebuild needs before it has read a
        single event: the board rows *are* the enumeration of projected subjects, because the
        projection never creates a record, only repaints the columns it owns.

        Paging is the pinned core convention (`pulse_core.twenty_deploy`, live-verified):
        `starting_after` with `pageInfo.hasNextPage` / `endCursor`. A page claiming a successor it
        gives no cursor for raises rather than loops.
        """
        records: list[Mapping[str, object]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": page_size}
            if filters:
                params["filter"] = ",".join(f"{field}[eq]:{value}" for field, value in sorted(filters.items()))
            if cursor is not None:
                params["starting_after"] = cursor
            try:
                response = self._http.get(f"{REST_ROOT}/{plural}", params=params)
            except httpx.TransportError as error:
                raise SubjectLookupError(status_code=None) from error
            if not response.is_success:
                raise SubjectLookupError(status_code=response.status_code)
            page, body = _records_of(response, plural)
            records.extend(page)
            page_info = body.get("pageInfo")
            if not isinstance(page_info, Mapping) or not cast("Mapping[str, object]", page_info).get("hasNextPage"):
                return tuple(records)
            end_cursor = cast("Mapping[str, object]", page_info).get("endCursor")
            if not isinstance(end_cursor, str) or not end_cursor:
                raise SubjectLookupError(
                    status_code=response.status_code,
                    detail=f"{plural} listing claims a next page with no endCursor",
                )
            cursor = end_cursor

    def patch_record(self, plural: str, record_id: str, fields: Mapping[str, object]) -> None:
        """One PATCH, success or a typed error — the failure body is dropped unread."""
        record_ref = f"{plural}:{record_id}"
        try:
            response = self._http.patch(f"{REST_ROOT}/{plural}/{record_id}", json=dict(fields))
        except httpx.TransportError as error:
            raise ProjectionWriteError(record_ref, status_code=None) from error
        if not response.is_success:
            raise ProjectionWriteError(record_ref, status_code=response.status_code)


def apply_event(
    envelope: Mapping[str, object],
    *,
    client: ProjectionRestClient,
    board: BoardTarget = V1_BOARD,
) -> ApplyResult:
    """Apply one committed event to its board record, monotonically, as one full-state PATCH.

    Returns `Applied` when the write happened, `SkippedStale` (after one identifiers-and-
    sequences-only log line) when the event's `seq` is at or below the record's watermark.
    Raises `MalformedEventError` for an envelope off the relay's shape, a
    `SubjectResolutionError` when no unique record matches, and `SubjectLookupError` /
    `ProjectionWriteError` when the transport fails — typed only, handling is task 2.2.
    """
    event = parse_envelope(envelope, board)
    record = _resolve_record(event, board, client)

    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise SubjectLookupError(status_code=None, detail="a matched record carried no id")
    record_ref = f"{board.object_name}:{record_id}"

    watermark = _watermark_of(record, board)
    if is_watermark_stale(event.seq, watermark):
        # is_watermark_stale is only true for a non-None watermark.
        stale_watermark = cast("int", watermark)
        logger.info(
            "projection no-op: event %s for subject %s program %s seq %s is at or below watermark %s on %s",
            event.event_id,
            event.subject_key,
            event.program,
            event.seq,
            stale_watermark,
            record_ref,
        )
        return SkippedStale(
            record_ref=record_ref,
            subject_key=event.subject_key,
            program=event.program,
            seq=event.seq,
            watermark=stale_watermark,
        )

    client.patch_record(board.plural, record_id, projected_fields(event, board))
    return Applied(record_ref=record_ref, subject_key=event.subject_key, program=event.program, seq=event.seq)


def projected_fields(event: EnrollmentEvent, board: BoardTarget = V1_BOARD) -> dict[str, object]:
    """The *whole* board state one event implies: encoded status, its as-of, and the watermark.

    The single place the projection decides what a record looks like after an event, so the
    incremental write path (`apply_event`) and the rebuild's fold (`twenty_projection.rebuild`)
    cannot disagree about it. A fold that built these fields itself would be a second
    implementation of the projection, and the rebuild would prove nothing about the first.

    Full state, not a delta (design decision 3): every field the projection owns is written on
    every apply, which is what makes out-of-band drift converge on the subject's next event —
    and what makes the last event in a subject's ledger sequence, per program, the whole answer
    a rebuild has to reproduce.
    """
    return {
        board.status_field: encode_option_value(event.to_state),
        board.as_of_field: event.effective_at,
        board.watermark_field: event.seq,
    }


@dataclass(frozen=True)
class EnrollmentEvent:
    """The envelope fields the apply core actually consumes, validated once at the boundary."""

    event_id: str
    subject_key: str
    program: str
    to_state: str
    seq: int
    effective_at: str


def parse_envelope(envelope: Mapping[str, object], board: BoardTarget) -> EnrollmentEvent:
    subject_type = envelope.get("subject_type")
    if subject_type != board.subject_type:
        raise MalformedEventError("subject_type")

    subject_key = _required_str(envelope, "subject_key")
    event_id = _required_str(envelope, "event_id")

    seq = envelope.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise MalformedEventError("seq")

    effective_at = _required_str(envelope, "effective_at")
    try:
        parsed = datetime.fromisoformat(effective_at)
    except ValueError as error:
        raise MalformedEventError("effective_at") from error
    if parsed.tzinfo is None:
        raise MalformedEventError("effective_at")

    raw_payload = envelope.get("payload")
    if not isinstance(raw_payload, Mapping):
        raise MalformedEventError("payload")
    payload = cast("Mapping[str, object]", raw_payload)
    to_state = payload.get("to_state")
    if not isinstance(to_state, str) or not to_state:
        raise MalformedEventError("payload.to_state")
    program = payload.get("program")
    if not isinstance(program, str) or not program:
        raise MalformedEventError("payload.program")

    # The filter grammar has no quoting: an identifier carrying a reserved character cannot be
    # expressed as a predicate, so it is refused here — before any request — never escaped.
    if FILTER_RESERVED & set(subject_key):
        raise MalformedEventError("subject_key")
    if FILTER_RESERVED & set(program):
        raise MalformedEventError("payload.program")

    return EnrollmentEvent(
        event_id=event_id,
        subject_key=subject_key,
        program=program,
        to_state=to_state,
        seq=seq,
        effective_at=effective_at,
    )


def _required_str(envelope: Mapping[str, object], field: str) -> str:
    value = envelope.get(field)
    if not isinstance(value, str) or not value:
        raise MalformedEventError(field)
    return value


def _resolve_record(event: EnrollmentEvent, board: BoardTarget, client: ProjectionRestClient) -> Mapping[str, object]:
    """The one board record for this subject, via the denormalized key columns — never guessed."""
    records = client.find_records(
        board.plural,
        {"canonicalPatientId": event.subject_key, "programCode": event.program},
    )
    if len(records) > 1:
        raise AmbiguousSubjectError(subject_key=event.subject_key, program=event.program, count=len(records))
    if not records:
        raise SubjectUnresolvedError(subject_key=event.subject_key, program=event.program)
    return records[0]


def _watermark_of(record: Mapping[str, object], board: BoardTarget) -> int | None:
    """The record's watermark: a NUMBER column, so an int, a float, or null (never projected)."""
    value = record.get(board.watermark_field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubjectLookupError(status_code=None, detail=f"{board.watermark_field} is not numeric")
    return int(value)


def _records_of(response: httpx.Response, plural: str) -> tuple[tuple[Mapping[str, object], ...], Mapping[str, object]]:
    """The records under `data.<plural>` and the body they came in, or a typed lookup error.

    Both listing verbs read the same envelope, so they read it in one place; the body is returned
    alongside because paging lives in `pageInfo` next to the records, not inside them. Nothing
    here quotes a value into an error — a shape complaint names the collection, never its content.
    """
    try:
        body: object = response.json()
    except ValueError as error:
        raise SubjectLookupError(status_code=response.status_code, detail="unparseable listing body") from error
    if not isinstance(body, Mapping):
        raise SubjectLookupError(status_code=response.status_code, detail="listing body is not a JSON object")
    envelope = cast("Mapping[str, object]", body)
    data: object = envelope.get("data")
    records: object = cast("Mapping[str, object]", data).get(plural) if isinstance(data, Mapping) else None
    if not isinstance(records, list):
        raise SubjectLookupError(status_code=response.status_code, detail=f"listing carried no {plural} collection")
    listed = cast("list[object]", records)
    return (
        tuple(cast("Mapping[str, object]", record) for record in listed if isinstance(record, Mapping)),
        envelope,
    )
