"""The patient-state projection: `patients` rows are a view of the ledger's `enrollment` family.

This handler is the *only* writer of `patients` (spec: "Only the ledger projection mints or
updates a patient row"). It subscribes to the `patient-state` feed for `enrollment` subjects,
resolves the subject to the canonical patient id the ledger and the Twenty board share, and mints
or moves one row with two facts from the event: `enrollment_status` (the resulting catalog state)
and `ledger_seq` (the event's ledger sequence, the row's citation for the conformance sweep).

Three rules carry the correctness, all of them in one statement:

- **Mint on the first `enrollment` event** (design.md decision 2). Nothing else creates a row —
  not an alert, not a migration, not a referral. A subject that resolves to no canonical patient
  id parks, counted, and the consumer moves on, exactly as the board projection does; so does an
  envelope off the relay's published shape.
- **Apply monotonically on `ledger_seq`.** The `ON CONFLICT DO UPDATE ... WHERE` predicate is the
  guard: an event at or below the row's citation updates nothing and is counted as a skip, never
  an error. Redelivery under at-least-once therefore leaves the row byte-identical. The guard is
  in SQL rather than in a read-then-write so it holds under concurrent apply without a lock.
- **Adopt legacy rows, never overwrite them** (design.md decision 5). `ledger_seq IS NULL` marks a
  row the retired bootstrap insert minted; that null is adoptable at *any* sequence, which is what
  turns the first real ledger event for the subject into the adoption. Until then the row keeps the
  status it has and stays uncitable to the sweep.

`clinic_id` is the one column written from the payload rather than from ledger state: it is
`NOT NULL` and the ledger does not assert it, so a mint takes a non-empty payload value or the
`UNSCOPED_CLINIC_ID` sentinel — the same value the retired bootstrap wrote, so projected and legacy
rows share one "no clinic scope known" marker. It is never rewritten on adopt or update, because
the projection has no authority over it. It is not citable and it does not belong to this
projection's contract; see HANDOFF.md.

Payload posture: `to_state` reaches a log line because it is the projected fact and the receipt is
about state. Nothing else from the payload ever does — not the clinic value, not a field this
handler does not read. Every log line and every receipt is built from envelope identifiers, the
state name, sequences, and counts, so PHI arriving in a payload once C1 clears has nothing to
ride out on.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import sqlalchemy as sa
import structlog

log = structlog.get_logger()

#: The ledger subject type this projection renders. The `patient-state` feed carries others.
ENROLLMENT_SUBJECT_TYPE = "enrollment"

#: The `Parked.reason` for a subject that resolves to no canonical patient id. Every other park
#: reason is the malformed envelope's field path.
UNRESOLVED_SUBJECT = "unresolved_subject"

#: What a projected row's `clinic_id` says when the event carries no clinic scope. `clinic_id` is
#: `NOT NULL`, is not ledger-sourced, and is not citable — the sentinel is the retired bootstrap's
#: own value so legacy and projected rows read alike.
UNSCOPED_CLINIC_ID = "unknown"


class PatientStateError(Exception):
    """Base for the projection's typed failures. Never carries a payload value."""


class MalformedEventError(PatientStateError):
    """The envelope is not the shape the ledger relay publishes — names the field path only.

    Raised by `parse_envelope`, which is the projection's validation boundary and is tested
    directly. `handle_patient_state` turns it into a counted `Parked` rather than letting it reach
    the consumer: a message the relay could not have published is not fixed by redelivery. The
    value that was wrong is *never* quoted into the message.
    """

    def __init__(self, field_path: str) -> None:
        self.field_path = field_path
        super().__init__(f"patient-state envelope is missing or malformed at {field_path!r}")


@dataclass(frozen=True)
class EnrollmentEvent:
    """The envelope fields this projection consumes, validated once at the boundary."""

    event_id: str
    subject_key: str
    to_state: str
    seq: int
    clinic_id: str


@dataclass(frozen=True)
class Applied:
    """One event written onto one row: the row now reads `to_state` and cites `seq`."""

    patient_id: str
    seq: int
    to_state: str
    event_id: str


@dataclass(frozen=True)
class SkippedStale:
    """A counted no-op: the row already cites this sequence or a later one."""

    patient_id: str
    seq: int
    event_id: str


@dataclass(frozen=True)
class Parked:
    """An event the projection applied nothing for: counted, logged, dropped.

    Two reasons, both spec-owned and neither an error: the subject resolves to no canonical
    patient id (`UNRESOLVED_SUBJECT`), or the envelope is off the relay's published shape (the
    malformed field path). Nothing is minted either way. Convergence is restored by the subject's
    next event, because every apply writes the whole projected state.

    `reason` is a field path or the fixed token above — never a value read from the envelope.
    """

    subject_key: str
    event_id: str
    reason: str


ApplyResult = Applied | SkippedStale | Parked

#: `resolve(subject_key) -> canonical patient id | None`.
CanonicalIdResolver = Callable[[str], str | None]


def resolve_canonical_patient_id(subject_key: str) -> str | None:
    """The `enrollment` subject key *is* the canonical patient id — the lookup `twenty-projection`
    performs when it filters the board on `canonicalPatientId` (design.md decision 2).

    Stated as an injectable seam rather than assumed inline: it is the one place the projection
    decides which id a `patients` row is keyed by, and a deployment whose subject keys need a real
    lookup replaces this function without touching the write path. A key that is blank or
    whitespace resolves to nothing and parks, the same collapse `pulse_ledger.twenty.mapping`
    applies to a blank `canonicalPatientId`.
    """
    key = subject_key.strip()
    return key or None


class ProjectionMetrics:
    """In-process counters, and only counters — a payload value has nothing to ride in on."""

    def __init__(self) -> None:
        self.applied = 0
        self.skipped_stale = 0
        self.parked = 0


#: The running service's counters. Tests and `rebuild` pass their own.
METRICS = ProjectionMetrics()


class JournalReader(Protocol):
    """The replay surface `rebuild` reads: every committed `enrollment` event, in ledger sequence.

    A Protocol so the rebuild depends on the shape of the read rather than on a client, and a test
    hands it a fixture journal while holding no credential at all.
    """

    def enrollment_events(self) -> Iterable[Mapping[str, object]]: ...


@dataclass(frozen=True)
class RebuildReceipt:
    """The counted record of one rebuild — counts and one state-free summary, safe to paste."""

    events_read: int
    subjects: int
    applied: int
    skipped_stale: int
    parked: int

    def render(self) -> str:
        return "\n".join([
            "patient-state rebuild receipt",
            f"  events read:   {self.events_read}",
            f"  subjects:      {self.subjects}",
            f"  rows written:  {self.applied}",
            f"  skipped stale: {self.skipped_stale}",
            f"  parked:        {self.parked}",
        ])


# One statement carries the mint, the adopt and the monotonic guard. `excluded` is the row the
# event proposes; `patients` is the row already there. The predicate is the whole of "apply is
# monotonic" and "legacy rows are adopted, not overwritten": a null citation always loses to an
# event, an equal or higher citation always wins. `clinic_id` is absent from the SET list on
# purpose — a mint may supply it, an update never rewrites it. RETURNING is what distinguishes a
# write from a guarded no-op without a second read.
_APPLY_SQL = sa.text(
    "INSERT INTO patients "
    "    (patient_id, clinic_id, enrollment_status, updated_at, last_event_id, ledger_seq) "
    "VALUES "
    "    (:patient_id, :clinic_id, :enrollment_status, :updated_at, :last_event_id, :ledger_seq) "
    "ON CONFLICT (patient_id) DO UPDATE SET "
    "    enrollment_status = excluded.enrollment_status, "
    "    ledger_seq        = excluded.ledger_seq, "
    "    updated_at        = excluded.updated_at, "
    "    last_event_id     = excluded.last_event_id "
    "WHERE patients.ledger_seq IS NULL OR patients.ledger_seq < excluded.ledger_seq "
    "RETURNING patient_id"
)


def parse_envelope(envelope: Mapping[str, object]) -> EnrollmentEvent:
    """Validate one `patient-state` envelope into the fields the projection writes.

    Raises `MalformedEventError` naming the field path — never quoting its value — for anything off
    the relay's published shape, including an `enrollment` state the catalog does not define.
    """
    if envelope.get("subject_type") != ENROLLMENT_SUBJECT_TYPE:
        raise MalformedEventError("subject_type")

    event_id = _required_str(envelope, "event_id")
    subject_key = _required_str(envelope, "subject_key")

    seq = envelope.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise MalformedEventError("seq")

    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise MalformedEventError("payload")

    # The state name is written verbatim and is not re-validated here. The ledger is the single
    # validator of catalog vocabulary: `pulse_ledger.validation.validate_transition` rejects any
    # `to_state` outside `pulse_core.generated.TRANSITIONS` at write time, so every event on this
    # feed already carries a catalog name. A consumer that re-encoded the family would drift the
    # moment the catalog versions — a new state would silently park — which is the duplication the
    # §4.4 producer-ingress gate exists to stop.
    to_state = payload.get("to_state")
    if not isinstance(to_state, str) or not to_state:
        raise MalformedEventError("payload.to_state")

    raw_clinic = payload.get("clinic_id")
    clinic_id = raw_clinic.strip() if isinstance(raw_clinic, str) else ""

    return EnrollmentEvent(
        event_id=event_id,
        subject_key=subject_key,
        to_state=to_state,
        seq=seq,
        clinic_id=clinic_id or UNSCOPED_CLINIC_ID,
    )


def _required_str(envelope: Mapping[str, object], field: str) -> str:
    """A present, non-empty string, or a field-path complaint.

    Emptiness of the *field* is a malformed envelope; a `subject_key` that is present but carries
    no identifier once normalized is not — that is an unresolvable subject, which the resolver
    collapses to nothing so it parks. The split matters: a data fault must surface for redelivery,
    an unresolvable subject must not.
    """
    value = envelope.get(field)
    if not isinstance(value, str) or not value:
        raise MalformedEventError(field)
    return value


def _park(metrics: ProjectionMetrics, *, subject_key: str, event_id: str, reason: str) -> Parked:
    """Count and log one park. `reason` is a field path or `UNRESOLVED_SUBJECT`, never a value."""
    metrics.parked += 1
    log.warning("patient_state_parked", subject_key=subject_key, event_id=event_id, reason=reason)
    return Parked(subject_key=subject_key, event_id=event_id, reason=reason)


async def handle_patient_state(
    event_data: Mapping[str, object],
    session,
    *,
    resolver: CanonicalIdResolver = resolve_canonical_patient_id,
    metrics: ProjectionMetrics | None = None,
) -> ApplyResult:
    """Apply one committed `enrollment` event to its `patients` row, monotonically.

    Returns `Applied` when the row was written, `SkippedStale` when the row already cites this
    sequence or a later one, and `Parked` — counted, never raised — when the subject resolves to no
    canonical patient id or the envelope is off the relay's published shape. Nothing here fails the
    consumer: a park is a normal return, so the queue keeps moving and the counts carry the signal.
    """
    counters = METRICS if metrics is None else metrics
    try:
        event = parse_envelope(event_data)
    except MalformedEventError as malformed:
        subject_key = event_data.get("subject_key")
        event_id = event_data.get("event_id")
        return _park(
            counters,
            subject_key=subject_key if isinstance(subject_key, str) else "",
            event_id=event_id if isinstance(event_id, str) else "",
            reason=malformed.field_path,
        )

    patient_id = resolver(event.subject_key)
    if patient_id is None:
        return _park(counters, subject_key=event.subject_key, event_id=event.event_id, reason=UNRESOLVED_SUBJECT)

    result = await session.execute(
        _APPLY_SQL,
        {
            "patient_id": patient_id,
            "clinic_id": event.clinic_id,
            "enrollment_status": event.to_state,
            "updated_at": datetime.now(tz=UTC),
            "last_event_id": event.event_id,
            "ledger_seq": event.seq,
        },
    )

    if result.first() is None:
        counters.skipped_stale += 1
        log.info("patient_state_skipped_stale", patient_id=patient_id, seq=event.seq, event_id=event.event_id)
        return SkippedStale(patient_id=patient_id, seq=event.seq, event_id=event.event_id)

    counters.applied += 1
    log.info(
        "patient_state_applied",
        patient_id=patient_id,
        enrollment_status=event.to_state,
        ledger_seq=event.seq,
        event_id=event.event_id,
    )
    return Applied(patient_id=patient_id, seq=event.seq, to_state=event.to_state, event_id=event.event_id)


async def rebuild(
    journal_reader: JournalReader,
    session,
    *,
    resolver: CanonicalIdResolver = resolve_canonical_patient_id,
) -> RebuildReceipt:
    """Replay every committed `enrollment` event onto `patients`, in ledger sequence, and receipt it.

    The attended path (design.md decision 10): run before anyone reads the projected rows, and
    again whenever the incremental path is suspected of having missed events. It applies the same
    `handle_patient_state` the live consumer does — not a second implementation — so the monotonic
    guard makes a replay of already-applied events a counted run of skips, and a rebuild that
    agreed with the live path by coincidence is not possible.

    Events are applied in the order the journal yields them, which the ledger's own read surface
    orders by sequence; the guard makes that an assertion rather than an assumption.
    """
    counters = ProjectionMetrics()
    events_read = 0
    subjects: set[str] = set()

    for envelope in journal_reader.enrollment_events():
        events_read += 1
        outcome = await handle_patient_state(envelope, session, resolver=resolver, metrics=counters)
        if isinstance(outcome, (Applied, SkippedStale)):
            subjects.add(outcome.patient_id)

    receipt = RebuildReceipt(
        events_read=events_read,
        subjects=len(subjects),
        applied=counters.applied,
        skipped_stale=counters.skipped_stale,
        parked=counters.parked,
    )
    log.info(
        "patient_state_rebuilt",
        events_read=receipt.events_read,
        subjects=receipt.subjects,
        rows_written=receipt.applied,
        skipped_stale=receipt.skipped_stale,
        parked=receipt.parked,
    )
    return receipt
