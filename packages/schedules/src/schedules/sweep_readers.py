"""Read-only readers for the reconciliation sweeps (task 1.3): every side a
`projection_conformance` sweep (task 2.1) reads before it can compare a subject, and nothing it
writes with — no reader in this module holds a command-submission or record-write method.

Four production readers, one shared fixture:

- **`LedgerStateReader`** — the ledger's own answer, read the same way every non-DB consumer of
  this ledger reads it: the command API's per-subject history (`PulseCoreClient.subject_history`,
  already the read boundary `pulse_core.client` ships), folded with `pulse_ledger.fold` — the one
  fold rule the commit path, this reader, and the warehouse's independent re-derivation all share,
  restated nowhere. Folding also yields the *snapshot head*: the highest `seq` this subject has
  committed, reversals included, which is what "one snapshot per run" (design.md decision 4) pins
  before any consumer is read. There is no bulk ledger enumeration here on purpose — the command
  API exposes no such route, and this reader is subject-at-a-time so the sweep never needs a
  ledger writer credential, or any direct database connection, to ask it a question.
- **`BoardReader`** — the Twenty projection's own read surface (`twenty_projection.apply
  .ProjectionRestClient.list_records`, the same paginated GET the projection's rebuild already
  uses), scoped to one board's projected columns plus the `ledger_seq` watermark it cites
  (`BoardFields`). Registering which board projects which family is task 3.2's job; this reader
  only knows how to read one, once told.
- **`LandingReader`** / **`RowCountReader`** — the fold view (task 1.2's
  `SUBJECT_CURRENT_STATE`) and an uncitable consumer's row count have no production client in this
  repo yet, so both stand on the same small `FamilyRowSource` / `FamilyCountSource` seam a live
  Snowflake adapter fills in later (`verdict_relay.production.SnowflakeRowSource` is the shape
  that adapter will take) — never on this reader's own DB connection or credential.
- **`PatientsReader`** (task 3.1) — `graph-projection-patients`' read surface once the projection
  is live: `patients` rows keyed by `patient_id`, carrying `enrollment_status` and `ledger_seq`
  (design.md decision 9). It reads the same `FamilyRowSource` seam as `LandingReader` rather than
  a new protocol, since the shape of "read one family's rows from somewhere" does not change —
  only the column names do. `ledger_seq` is nullable *by design*, never malformed: a legacy row
  (design.md decision 5, "Legacy rows are marked, never overwritten") parses cleanly with
  `cited_seq=None`, which `projection_conformance` turns into `uncitable` for that one row, never
  `state` and never dropped.
- **`FixtureReader`** — the one seam implementation this task ships: an in-memory
  `FamilyRowSource`/`FamilyCountSource` over recorded rows, which is every `LandingReader` /
  `RowCountReader` / `PatientsReader` test's fixture today and stays the offline `--dry-run` path
  once live wiring lands, the same posture `consent_sweep.load_ledger_state_fixture` already
  established. `LedgerStateReader` and `BoardReader` need no fixture double of their own: both
  already test against `httpx.MockTransport`, this package's and the wider repo's own convention.

Every reader answers a malformed row by counting it, never by raising past it (spec:
"Malformed rows are counted and attached") — a `MalformedRow` names a row's position and what was
wrong with it, never the row's other contents, so a receipt built over these results is safe to
log whole. A transport failure (the source is unreachable, refuses the request) is not a malformed
row and is left to raise: that is "the sweep could not run", not "one row of it disagreed".
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from pulse_ledger.fold import FoldedEvent, fold_state, state_borne_by
from twenty_projection.apply import BoardTarget, ProjectionRestClient

__all__ = [
    "BoardFields",
    "BoardReader",
    "FamilyCountSource",
    "FamilyRead",
    "FamilyRowSource",
    "FixtureReader",
    "LandingReader",
    "LedgerStateReader",
    "MalformedEnvelopeError",
    "MalformedRow",
    "PatientsReader",
    "RowCountReader",
    "SubjectHistorySource",
    "SubjectRead",
    "SweptRow",
]


@dataclass(frozen=True)
class SweptRow:
    """One subject's state as one reader saw it: the fields that reader's own schema projects
    (named, never any value beyond a small state string — no PHI, no payload) and the ledger
    sequence it cites for that state, when it cites one at all (`None` for an uncitable reader,
    never for `LedgerStateReader` or `BoardReader`)."""

    subject_key: str
    fields: Mapping[str, str]
    cited_seq: int | None


@dataclass(frozen=True)
class MalformedRow:
    """One row a reader could not parse. Names the row's position and what was wrong with it —
    never the row's other contents, which may carry values a receipt must never hold."""

    position: str
    detail: str


@dataclass(frozen=True)
class FamilyRead:
    """One family's read from one consumer: every row that parsed, and every row that did not.

    A malformed row is counted here rather than dropped (spec: "Malformed rows are counted and
    attached") — `rows` and `malformed` are independent tallies over the same read, not a
    filtered/rejected pair, so nothing this reader saw goes unaccounted.
    """

    rows: list[SweptRow]
    malformed: list[MalformedRow]


@dataclass(frozen=True)
class SubjectRead:
    """One subject's ledger read: its folded state (`None` — no state row, never an error, for a
    subject the ledger has never seen), any individual event that failed to parse out of its
    history, and when the head was committed.

    `head_recorded_at` is the `recorded_at` of the event the head sequence belongs to — the same
    history read the fold already walked, kept rather than re-derived, because it is what the
    freshness budget and the completeness floor are measured against (design.md decisions 4 and 5).
    `None` when no event carried a readable one; the classifier then grants no freshness grace and
    applies no floor exclusion.
    """

    row: SweptRow | None
    malformed: list[MalformedRow]
    head_recorded_at: datetime | None = None


# --- LedgerStateReader ---------------------------------------------------------------------


class SubjectHistorySource(Protocol):
    """Where one subject's committed history comes from. `PulseCoreClient.subject_history`
    already matches this shape — the command API's read boundary, no adapter needed."""

    def subject_history(self, subject_type: str, subject_key: str) -> Sequence[Mapping[str, object]]: ...


class MalformedEnvelopeError(ValueError):
    """One event envelope's first structural violation — caught by `LedgerStateReader` into a
    `MalformedRow`, never raised past the event it names."""


def _required_uuid(envelope: Mapping[str, object], field: str) -> uuid.UUID:
    value = envelope.get(field)
    if not isinstance(value, str):
        msg = f"{field} is not a string"
        raise MalformedEnvelopeError(msg)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        msg = f"{field} is not a UUID"
        raise MalformedEnvelopeError(msg) from exc


def _required_instant(envelope: Mapping[str, object], field: str) -> datetime:
    value = envelope.get(field)
    if not isinstance(value, str):
        msg = f"{field} is not a string"
        raise MalformedEnvelopeError(msg)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"{field} is not ISO-8601"
        raise MalformedEnvelopeError(msg) from exc


def _optional_uuid(envelope: Mapping[str, object], field: str) -> uuid.UUID | None:
    value = envelope.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field} is not a string"
        raise MalformedEnvelopeError(msg)
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        msg = f"{field} is not a UUID"
        raise MalformedEnvelopeError(msg) from exc


def _folded_event_or_none(envelope: Mapping[str, object]) -> FoldedEvent | None:
    """One envelope, folded — or `None` when it never contributes to a fold at all.

    Mirrors `pulse_ledger.commit.load_folded_events`'s own rule exactly, the one place this fold
    candidacy check is otherwise stated: a reversal is kept even when it bears no state of its
    own (the fold needs it to know which event it voids), and a non-state-bearing, non-reversal
    event never contributed state and is simply not part of the fold.

    Raises `MalformedEnvelopeError` for an event this rule keeps whose shape the fold itself
    needs and cannot read: a missing/non-UUID `event_id`, or a missing/non-ISO-8601
    `effective_at` / `recorded_at`.
    """
    payload = envelope.get("payload")
    to_state = state_borne_by(cast("Mapping[str, object]", payload)) if isinstance(payload, Mapping) else None
    reverses_event_id = _optional_uuid(envelope, "reverses_event_id")
    if to_state is None and reverses_event_id is None:
        return None
    return FoldedEvent(
        event_id=_required_uuid(envelope, "event_id"),
        to_state=to_state or "",
        effective_at=_required_instant(envelope, "effective_at"),
        recorded_at=_required_instant(envelope, "recorded_at"),
        reverses_event_id=reverses_event_id,
    )


def _head_seq(envelope: Mapping[str, object]) -> int | None:
    seq = envelope.get("seq")
    return seq if isinstance(seq, int) else None


def _recorded_at(envelope: Mapping[str, object]) -> datetime | None:
    """One envelope's commit time, or `None` when it carries none this reader can read. Read
    leniently on purpose: an unparseable `recorded_at` on the head costs the subject its freshness
    grace, which is the conservative outcome, and never fails the read."""
    try:
        return _required_instant(envelope, "recorded_at")
    except MalformedEnvelopeError:
        return None


class LedgerStateReader:
    """One subject's current ledger state and its snapshot head — the command API's per-subject
    history read, folded, never a direct ledger connection (design.md decision 2: no ledger
    writer credential, no ledger-internal surface).
    """

    def __init__(self, source: SubjectHistorySource) -> None:
        self._source = source

    def read_subject(self, subject_type: str, subject_key: str) -> SubjectRead:
        """The subject's folded state plus the highest `seq` it has committed (reversals
        included — the snapshot head is "how far this subject's history goes", not "how far its
        surviving state goes"), pinned once at read time per design.md decision 4.

        An event that fails to parse is counted as `malformed` and dropped from the fold; the
        remaining events still fold normally, and a subject whose entire history is unparseable
        folds to `row=None` with every event named in `malformed` rather than raising.
        """
        envelopes = self._source.subject_history(subject_type, subject_key)
        folded_events: list[FoldedEvent] = []
        malformed: list[MalformedRow] = []
        head_seq: int | None = None
        head_recorded_at: datetime | None = None
        for index, envelope in enumerate(envelopes):
            seq = _head_seq(envelope)
            if seq is not None and (head_seq is None or seq > head_seq):
                head_seq = seq
                head_recorded_at = _recorded_at(envelope)
            try:
                folded = _folded_event_or_none(envelope)
            except MalformedEnvelopeError as exc:
                malformed.append(MalformedRow(position=f"[event offset {index}]", detail=str(exc)))
                continue
            if folded is not None:
                folded_events.append(folded)

        state = fold_state(folded_events)
        row = (
            None
            if state is None
            else SweptRow(subject_key=subject_key, fields={"state": state.state}, cited_seq=head_seq)
        )
        return SubjectRead(row=row, malformed=malformed, head_recorded_at=head_recorded_at)


# --- BoardReader ----------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardFields:
    """One board's read shape: the Twenty object and the columns a sweep reads off it — the
    projection's own `BoardTarget` (object, plural, watermark column) plus the identity column a
    sweep resolves a subject key from and the fields it compares, per family (task 3.2 wires
    which board projects which family; this dataclass only knows how to read one once told).
    """

    board: BoardTarget
    subject_key_field: str
    compared_fields: tuple[str, ...]


class BoardReader:
    """The Twenty projection's read surface: projected fields plus `ledger_seq`, paginated per
    family (design.md decision 6) — `ProjectionRestClient.list_records`, the identical GET the
    projection's own rebuild pages with. No PATCH, no comment post: this reader holds no method
    that writes Twenty.
    """

    def __init__(self, client: ProjectionRestClient) -> None:
        self._client = client

    def read_family(self, fields: BoardFields, *, filters: Mapping[str, str] | None = None) -> FamilyRead:
        records = self._client.list_records(fields.board.plural, filters=filters)
        rows: list[SweptRow] = []
        malformed: list[MalformedRow] = []
        for index, record in enumerate(records):
            subject_key = record.get(fields.subject_key_field)
            if not isinstance(subject_key, str) or not subject_key:
                malformed.append(
                    MalformedRow(
                        position=f"[offset {index}]",
                        detail=f"missing or empty {fields.subject_key_field!r}",
                    )
                )
                continue
            cited_seq = record.get(fields.board.watermark_field)
            if not isinstance(cited_seq, int):
                malformed.append(
                    MalformedRow(position=subject_key, detail=f"{fields.board.watermark_field!r} is not an int")
                )
                continue
            row_fields: dict[str, str] = {}
            missing_field: str | None = None
            for name in fields.compared_fields:
                value = record.get(name)
                if not isinstance(value, str) or not value:
                    missing_field = name
                    break
                row_fields[name] = value
            if missing_field is not None:
                malformed.append(MalformedRow(position=subject_key, detail=f"missing or empty {missing_field!r}"))
                continue
            rows.append(SweptRow(subject_key=subject_key, fields=row_fields, cited_seq=cited_seq))
        return FamilyRead(rows=rows, malformed=malformed)


# --- LandingReader / RowCountReader / FixtureReader ------------------------------------------


class FamilyRowSource(Protocol):
    """Where one family's landing rows come from — the fold view in production (task 1.2's
    `SUBJECT_CURRENT_STATE`, once a live adapter wires it), a fixture in every test today."""

    def fetch_family(self, family: str) -> Sequence[Mapping[str, object]]: ...


class FamilyCountSource(Protocol):
    """Where one family's row count comes from, for a consumer that cites nothing per row."""

    def count_family(self, family: str) -> int: ...


class LandingReader:
    """The fold view's read surface: one row per subject, the state its latest landed event
    carries and the sequence it cites (design.md decision 3)."""

    def __init__(self, source: FamilyRowSource) -> None:
        self._source = source

    def read_family(self, family: str) -> FamilyRead:
        rows: list[SweptRow] = []
        malformed: list[MalformedRow] = []
        for index, raw in enumerate(self._source.fetch_family(family)):
            subject_key = raw.get("subject_key")
            if not isinstance(subject_key, str) or not subject_key:
                malformed.append(MalformedRow(position=f"[offset {index}]", detail="missing or empty 'subject_key'"))
                continue
            state = raw.get("state")
            if not isinstance(state, str) or not state:
                malformed.append(MalformedRow(position=subject_key, detail="missing or empty 'state'"))
                continue
            seq = raw.get("seq")
            if not isinstance(seq, int):
                malformed.append(MalformedRow(position=subject_key, detail="'seq' is not an int"))
                continue
            rows.append(SweptRow(subject_key=subject_key, fields={"state": state}, cited_seq=seq))
        return FamilyRead(rows=rows, malformed=malformed)


class PatientsReader:
    """`graph-projection-patients`' read surface (task 3.1, design.md decision 9): one row per
    `patients` row, the state it projects and the ledger sequence it cites — nullable, since a
    legacy row (design.md decision 5) has none.
    """

    def __init__(self, source: FamilyRowSource) -> None:
        self._source = source

    def read_family(self, family: str) -> FamilyRead:
        rows: list[SweptRow] = []
        malformed: list[MalformedRow] = []
        for index, raw in enumerate(self._source.fetch_family(family)):
            patient_id = raw.get("patient_id")
            if not isinstance(patient_id, str) or not patient_id:
                malformed.append(MalformedRow(position=f"[offset {index}]", detail="missing or empty 'patient_id'"))
                continue
            enrollment_status = raw.get("enrollment_status")
            if not isinstance(enrollment_status, str) or not enrollment_status:
                malformed.append(MalformedRow(position=patient_id, detail="missing or empty 'enrollment_status'"))
                continue
            ledger_seq = raw.get("ledger_seq")
            if ledger_seq is not None and not isinstance(ledger_seq, int):
                # `None` is a legacy row, never malformed (design.md decision 5); anything else
                # that is not an int is an unreadable citation.
                malformed.append(MalformedRow(position=patient_id, detail="'ledger_seq' is not an int or null"))
                continue
            rows.append(SweptRow(subject_key=patient_id, fields={"state": enrollment_status}, cited_seq=ledger_seq))
        return FamilyRead(rows=rows, malformed=malformed)


class RowCountReader:
    """An uncitable consumer's whole read surface: a row count per family, nothing per-subject
    (design.md decision 6 — `graph-projection-patients`, reported as a class with a count and its
    owning change, never compared subject by subject)."""

    def __init__(self, source: FamilyCountSource) -> None:
        self._source = source

    def read_family(self, family: str) -> int:
        return self._source.count_family(family)


@dataclass(frozen=True)
class FixtureReader:
    """A `FamilyRowSource` and `FamilyCountSource` over recorded rows, keyed by family — every
    `LandingReader` / `RowCountReader` test's implementation, and today's only implementation,
    full stop: a live warehouse adapter and a live uncitable-consumer count wire in through this
    same pair of narrow protocols without either reader changing shape.
    """

    rows_by_family: Mapping[str, Sequence[Mapping[str, object]]]

    def fetch_family(self, family: str) -> Sequence[Mapping[str, object]]:
        return tuple(self.rows_by_family.get(family, ()))

    def count_family(self, family: str) -> int:
        return len(self.rows_by_family.get(family, ()))
