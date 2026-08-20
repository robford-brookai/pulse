"""The commit path: one transaction writes the event, the subject's state, and the outbox row.

Design decisions this implements (pulse-ledger-core §Decisions 1, 3, 5):

- **One transaction, three rows.** `events` (append), `current_state` (co-commit), `outbox`
  (per-subject `seq`). A reader never sees the event without the state, or the outbox row without
  the event, and a failure anywhere leaves none of them. Called from outside a transaction — the
  service's own posture — the three rows are durable when the function returns. Called from inside
  one, `conn.transaction()` degrades to a savepoint: the three rows are still all-or-nothing
  relative to each other, but the returned `CommitResult` describes a write that the outer
  transaction can still abort, so a caller composing commits (task 3.3's idempotency key insert is
  the intended one) owns that boundary and must not answer a client until it has committed.
- **`recorded_at` is the server's.** It is never accepted from a caller: `Declaration` has no such
  field and `from_mapping` rejects the key outright. The column default (`now()`) sets it and the
  insert returns it.
- **`effective_at` is canonical, `occurred_at` is an accepted input alias** — normalised at the
  boundary in `from_mapping`, so nothing downstream of it knows the alias exists.
- **Correction is by reversal, never by edit.** `commit_reversal` appends an event referencing the
  one it voids; both stay readable, and the subject's state is re-folded without them.

`current_state` is recomputed by folding the subject's surviving events rather than by writing the
new event's `to_state` straight through. That is what makes a backdated declaration behave: it
commits, it joins history, and it does not become the current state unless it is genuinely the
latest fact. It also makes the co-committed row equal to the independent re-derivation by
construction, which is the property task 5.1 asserts. The cost is one indexed per-subject read per
commit, bounded by that subject's event count.

Concurrency: a per-subject advisory lock, held for the transaction, serialises the
read-fold-then-write. Without it two commits for the same subject could interleave between the
fold and the write and leave `current_state` reflecting the loser, or collide on the outbox `seq`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pulse_core.generated import CATALOG_VERSION

from pulse_ledger.fold import TO_STATE_KEY, FoldedEvent, FoldedState, fold_state, state_as_of, state_borne_by
from pulse_ledger.validation import (
    validate_first_transition,
    validate_state_membership,
    validate_subject_type,
    validate_transition,
)

#: Input alias for `effective_at`, accepted for envelope compatibility (decision 5).
EFFECTIVE_AT_ALIAS = "occurred_at"

#: Fields the server owns; a caller supplying one is a bug, not a preference.
SERVER_SET_FIELDS = frozenset({"recorded_at", "event_id", "rule_version"})


class DeclarationError(ValueError):
    """A declaration the boundary refuses before any validation or write happens."""


class ServerSetFieldError(DeclarationError):
    """The caller supplied a field the server sets."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} is set by the server and must not be supplied by a writer")


class ConflictingEffectiveAtError(DeclarationError):
    """Both `effective_at` and its alias were supplied, with different values."""

    def __init__(self, effective_at: object, occurred_at: object) -> None:
        super().__init__(
            f"'effective_at' ({effective_at!r}) and {EFFECTIVE_AT_ALIAS!r} ({occurred_at!r}) disagree; "
            f"{EFFECTIVE_AT_ALIAS!r} is an alias, not a second field"
        )


class MissingEffectiveAtError(DeclarationError):
    """Neither `effective_at` nor its alias was supplied."""

    def __init__(self) -> None:
        super().__init__(f"a declaration needs 'effective_at' (or its alias {EFFECTIVE_AT_ALIAS!r})")


class NaiveTimestampError(DeclarationError):
    """A timestamp arrived without a timezone, so its instant is not determined."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} must be timezone-aware; a naive timestamp has no determined instant")


class UnknownEventError(LookupError):
    """A reversal names an event the ledger does not hold."""

    def __init__(self, event_id: uuid.UUID) -> None:
        self.event_id = event_id
        super().__init__(f"no committed event {event_id}")


class AlreadyReversedError(ValueError):
    """A reversal names an event another reversal already voided."""

    def __init__(self, event_id: uuid.UUID, reversal_id: uuid.UUID) -> None:
        self.event_id = event_id
        self.reversal_id = reversal_id
        super().__init__(f"event {event_id} was already reversed by {reversal_id}")


class ReversalLeavesNoStateError(ValueError):
    """The reversal would void a subject's last surviving state-bearing event."""

    def __init__(self, subject_type: str, subject_key: str) -> None:
        self.subject_type = subject_type
        self.subject_key = subject_key
        super().__init__(
            f"reversing this event leaves {subject_type}/{subject_key} with no state; "
            "a subject's first fact is corrected by declaring a new one, not by reversal"
        )


@dataclass(frozen=True)
class Declaration:
    """One fact a writer declares about one subject.

    Carries no `recorded_at`, no `event_id` and no `rule_version`: those are the server's, and
    leaving them off the type is what makes that structural rather than documented.

    `to_state` is optional: a subject-moving fact carries it, a non-state-bearing one
    (`resolution_hold`, `reconstruction_gap` — task 3.5) does not, and `commit_declaration` skips
    catalog-transition validation and the state re-fold for the latter.
    """

    subject_type: str
    subject_key: str
    event_type: str
    effective_at: datetime
    actor_type: str
    actor_id: str
    producer: str
    to_state: str | None = None
    # The actor's authority to declare this fact (a role, a delegation) — resolved from the
    # credential by task 3.4's auth layer, which is why it is optional here.
    actor_authority: str | None = None
    evidence_class: str = "E0"
    epoch: str = "declared"
    # `evidence` and `payload` are the two schema-free fields, and the two that will carry PHI once
    # C1 clears (`design/platform/event-envelope-spec.md`). They are kept out of the generated repr
    # so a `logger.exception(...)` or an error tracker capturing frame locals cannot render a
    # patient payload into a log sink. Structural, rather than a rule every future caller must
    # remember.
    evidence: Mapping[str, object] | None = field(default=None, repr=False)
    evidence_bounds: tuple[datetime, datetime] | None = None
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    payload: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        _require_aware(self.effective_at, "effective_at")
        if self.evidence_bounds is not None:
            _require_aware(self.evidence_bounds[0], "evidence_bounds[0]")
            _require_aware(self.evidence_bounds[1], "evidence_bounds[1]")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Declaration:
        """Build a declaration from a raw request body, normalising the `occurred_at` alias."""
        for name in SERVER_SET_FIELDS:
            if name in data:
                raise ServerSetFieldError(name)
        fields = dict(data)
        effective_at = fields.pop("effective_at", None)
        occurred_at = fields.pop(EFFECTIVE_AT_ALIAS, None)
        if effective_at is not None and occurred_at is not None and effective_at != occurred_at:
            raise ConflictingEffectiveAtError(effective_at, occurred_at)
        resolved = effective_at if effective_at is not None else occurred_at
        if resolved is None:
            raise MissingEffectiveAtError()
        return cls(effective_at=resolved, **fields)  # type: ignore[arg-type]

    def event_payload(self) -> dict[str, object]:
        """The stored payload: the writer's fields plus the state this event moves the subject to.

        A non-state-bearing declaration (`to_state` is `None`) carries no `to_state` key at all,
        rather than one holding `null` — `fold.state_borne_by` treats both the same, but leaving
        the key out is what makes "this event is not state-bearing" visible in the stored payload
        itself, not just in the type that produced it.
        """
        payload = dict(self.payload)
        if self.to_state is not None:
            payload[TO_STATE_KEY] = self.to_state
        return payload


@dataclass(frozen=True)
class CommitResult:
    """What a commit produced, as the API's response is built from.

    `replayed` distinguishes a fresh commit from the answer to a repeated idempotency key, which is
    the `committed | replayed` half of the client's response classification (decision 6). Only
    `pulse_ledger.idempotency` sets it: a commit that reaches this module is by definition new.
    """

    event_id: uuid.UUID
    recorded_at: datetime
    rule_version: str
    outbox_seq: int
    state: FoldedState | None
    replayed: bool = False


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveTimestampError(name)


def _lock_subject(conn: psycopg.Connection, subject_type: str, subject_key: str) -> None:
    """Serialise this subject's commits for the rest of the transaction.

    `hashtextextended` gives the 64-bit key the advisory lock wants. Collisions between distinct
    subjects cost a needless wait, never a wrong answer.
    """
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{subject_type}\x1f{subject_key}",),
    )


def load_folded_events(conn: psycopg.Connection, subject_type: str, subject_key: str) -> list[FoldedEvent]:
    """Every state-bearing event for one subject, for folding.

    Public because the replay path re-derives the state an earlier commit produced from the same
    history (`pulse_ledger.idempotency`), and two readings of "which events are part of a fold"
    would be two answers.
    """
    cursor = conn.execute(
        "SELECT event_id, payload, effective_at, recorded_at, reverses_event_id"
        " FROM ledger.events WHERE subject_type = %s AND subject_key = %s",
        (subject_type, subject_key),
    )
    events: list[FoldedEvent] = []
    for event_id, payload, effective_at, recorded_at, reverses_event_id in cursor.fetchall():
        to_state = state_borne_by(payload)
        # A reversal is kept even when it bears no state of its own: the fold needs it to know
        # which event it voids. A non-state-bearing, non-reversal event (`reconstruction_gap`)
        # never contributed state and is simply not part of the fold.
        if to_state is None and reverses_event_id is None:
            continue
        events.append(
            FoldedEvent(
                event_id=event_id,
                to_state=to_state or "",
                effective_at=effective_at,
                recorded_at=recorded_at,
                reverses_event_id=reverses_event_id,
            )
        )
    return events


#: Every column the commit path binds a value to. `schema_version` is absent on purpose — its server
#: default sets it — and `recorded_at` is set by a server-side expression below rather than bound.
#: Fixed and literal, so the insert statement is a constant and no caller-shaped identifier ever
#: reaches SQL.
_EVENT_COLUMNS = (
    "event_id",
    "subject_type",
    "subject_key",
    "event_type",
    "effective_at",
    "producer",
    "rule_version",
    "actor_type",
    "actor_id",
    "actor_authority",
    "evidence",
    "evidence_class",
    "evidence_bound_lower",
    "evidence_bound_upper",
    "epoch",
    "reverses_event_id",
    "correlation_id",
    "causation_id",
    "payload",
)

# `clock_timestamp()`, not the column's `now()` default: `now()` is `transaction_timestamp()` and is
# frozen for the whole transaction, so two events committed inside one caller-owned transaction
# would share a `recorded_at` — collapsing the fold's tie-break and breaking `state_as_of`'s
# invariant that a new event is always the latest-recorded. Still server-set: it is an expression
# evaluated by Postgres, never a value a writer can supply.
_INSERT_EVENT_SQL = sql.SQL(
    "INSERT INTO ledger.events ({columns}, recorded_at)"
    " VALUES ({placeholders}, clock_timestamp()) RETURNING recorded_at"
).format(
    columns=sql.SQL(", ").join(sql.Identifier(column) for column in _EVENT_COLUMNS),
    placeholders=sql.SQL(", ").join(sql.Placeholder(column) for column in _EVENT_COLUMNS),
)


def _insert_event(conn: psycopg.Connection, **values: Any) -> datetime:
    """Append one event and return the server-set `recorded_at`."""
    row: dict[str, Any] = dict.fromkeys(_EVENT_COLUMNS)
    row.update(values)
    cursor = conn.execute(_INSERT_EVENT_SQL, row)
    recorded_at: datetime = cursor.fetchone()[0]  # type: ignore[index]
    return recorded_at


def _insert_outbox_row(conn: psycopg.Connection, event_id: uuid.UUID, subject_type: str, subject_key: str) -> int:
    """Enqueue the event for relay at the next per-subject sequence number (D17)."""
    cursor = conn.execute(
        "INSERT INTO ledger.outbox (event_id, subject_type, subject_key, seq)"
        " SELECT %(event_id)s, %(subject_type)s, %(subject_key)s,"
        "        coalesce(max(seq), 0) + 1 FROM ledger.outbox"
        "        WHERE subject_type = %(subject_type)s AND subject_key = %(subject_key)s"
        " RETURNING seq",
        {"event_id": event_id, "subject_type": subject_type, "subject_key": subject_key},
    )
    seq: int = cursor.fetchone()[0]  # type: ignore[index]
    return seq


def _refold_and_write(
    conn: psycopg.Connection,
    subject_type: str,
    subject_key: str,
    history: list[FoldedEvent],
) -> FoldedState | None:
    """Co-commit the subject's state as the fold computes it from `history`.

    Returns `None` when nothing survives the fold — every event reversed. There is no state to
    write then, and no way to unwrite the row either: `current_state` is INSERT/UPDATE-only for the
    service role, deliberately. `commit_reversal` refuses that case rather than leaving a stale row
    behind; `commit_declaration` cannot reach it, because the event it just appended always
    survives.
    """
    folded = fold_state(history)
    if folded is None:
        return None
    conn.execute(
        "INSERT INTO ledger.current_state"
        " (subject_type, subject_key, state, effective_at, last_event_id, updated_at)"
        " VALUES (%(subject_type)s, %(subject_key)s, %(state)s, %(effective_at)s, %(event_id)s, %(recorded_at)s)"
        " ON CONFLICT (subject_type, subject_key) DO UPDATE SET"
        "   state = EXCLUDED.state,"
        "   effective_at = EXCLUDED.effective_at,"
        "   last_event_id = EXCLUDED.last_event_id,"
        "   updated_at = EXCLUDED.updated_at",
        {
            "subject_type": subject_type,
            "subject_key": subject_key,
            "state": folded.state,
            "effective_at": folded.effective_at,
            "event_id": folded.event_id,
            "recorded_at": folded.recorded_at,
        },
    )
    return folded


def commit_declaration(
    conn: psycopg.Connection,
    declaration: Declaration,
    *,
    allow_arbitrary_genesis: bool = False,
) -> CommitResult:
    """Validate and commit one declaration: event, co-committed state, outbox row, one transaction.

    `allow_arbitrary_genesis` lets a subject's first event land at a non-entry state. Only the
    backfill vocabulary may set it (task 3.5); the forward path must not.

    A declaration with no `to_state` (`resolution_hold`, `reconstruction_gap` — task 3.5) is not a
    transition: it skips catalog-transition validation (only the subject type is checked) and never
    joins the fold, so `current_state` is left exactly as it was — there is no state for a hold or a
    gap to move the subject to or away from.

    Raises `IllegalTransitionError` before any write when the catalog forbids the transition, or
    (for a non-state-bearing declaration) names an unknown subject type.
    """
    with conn.transaction():
        _lock_subject(conn, declaration.subject_type, declaration.subject_key)
        history = load_folded_events(conn, declaration.subject_type, declaration.subject_key)
        if declaration.to_state is None:
            validate_subject_type(declaration.subject_type)
            rule_version = CATALOG_VERSION
        else:
            predecessor = state_as_of(history, declaration.effective_at)
            if predecessor is not None:
                # A backdated declaration departs from the state that held when its fact was true,
                # not from the subject's latest state — same call, different predecessor.
                rule_version = validate_transition(declaration.subject_type, predecessor.state, declaration.to_state)
            elif allow_arbitrary_genesis:
                # The flag relaxes the entry-state rule only. The state must still be one the
                # catalog contains, or a typo lands in `current_state` stamped as catalog-conformant.
                rule_version = validate_state_membership(declaration.subject_type, declaration.to_state)
            else:
                rule_version = validate_first_transition(declaration.subject_type, declaration.to_state)

        event_id = uuid.uuid4()
        lower, upper = declaration.evidence_bounds or (None, None)
        recorded_at = _insert_event(
            conn,
            event_id=event_id,
            subject_type=declaration.subject_type,
            subject_key=declaration.subject_key,
            event_type=declaration.event_type,
            effective_at=declaration.effective_at,
            producer=declaration.producer,
            rule_version=rule_version,
            actor_type=declaration.actor_type,
            actor_id=declaration.actor_id,
            actor_authority=declaration.actor_authority,
            evidence=Jsonb(dict(declaration.evidence)) if declaration.evidence is not None else None,
            evidence_class=declaration.evidence_class,
            evidence_bound_lower=lower,
            evidence_bound_upper=upper,
            epoch=declaration.epoch,
            correlation_id=declaration.correlation_id,
            causation_id=declaration.causation_id,
            payload=Jsonb(declaration.event_payload()),
        )
        if declaration.to_state is None:
            # Not state-bearing: `load_folded_events` would skip this row too, so folding the
            # unchanged history back is a no-op — `current_state` is not written at all.
            folded = fold_state(history)
        else:
            history.append(
                FoldedEvent(
                    event_id=event_id,
                    to_state=declaration.to_state,
                    effective_at=declaration.effective_at,
                    recorded_at=recorded_at,
                )
            )
            folded = _refold_and_write(conn, declaration.subject_type, declaration.subject_key, history)
        seq = _insert_outbox_row(conn, event_id, declaration.subject_type, declaration.subject_key)

    return CommitResult(
        event_id=event_id,
        recorded_at=recorded_at,
        rule_version=rule_version,
        outbox_seq=seq,
        state=folded,
    )


def commit_reversal(
    conn: psycopg.Connection,
    *,
    reverses_event_id: uuid.UUID,
    actor_type: str,
    actor_id: str,
    producer: str,
    reason: str,
    evidence_class: str = "E0",
    epoch: str = "declared",
    correlation_id: uuid.UUID | None = None,
    causation_id: uuid.UUID | None = None,
) -> CommitResult:
    """Correct a committed event by appending the reversal that voids it (I7).

    The voided event is never touched — the store would refuse anyway. Both events stay readable in
    history; the subject's state is re-folded with neither of them contributing. The reversal
    carries the voided event's `effective_at`, so it sorts adjacent to what it undoes, and its
    `recorded_at` is the server's, as every event's is.

    Raises `UnknownEventError` if the target is not in the ledger, `AlreadyReversedError` if
    another reversal already voided it, and `ReversalLeavesNoStateError` if it is the subject's
    only surviving state.
    """
    with conn.transaction():
        target = conn.execute(
            "SELECT subject_type, subject_key, event_type, effective_at FROM ledger.events WHERE event_id = %s",
            (reverses_event_id,),
        ).fetchone()
        if target is None:
            raise UnknownEventError(reverses_event_id)
        subject_type, subject_key, event_type, effective_at = target

        _lock_subject(conn, subject_type, subject_key)
        existing = conn.execute(
            "SELECT event_id FROM ledger.events WHERE reverses_event_id = %s",
            (reverses_event_id,),
        ).fetchone()
        if existing is not None:
            raise AlreadyReversedError(reverses_event_id, existing[0])

        history = load_folded_events(conn, subject_type, subject_key)
        event_id = uuid.uuid4()
        recorded_at = _insert_event(
            conn,
            event_id=event_id,
            subject_type=subject_type,
            subject_key=subject_key,
            event_type=f"{event_type}.reversed",
            effective_at=effective_at,
            producer=producer,
            rule_version=CATALOG_VERSION,
            actor_type=actor_type,
            actor_id=actor_id,
            # A reversal is its own act of declaration, not an echo of the fact it withdraws: it
            # inherits neither the voided event's evidence class nor its epoch. A backfill process
            # correcting reconstructed history overrides both.
            evidence_class=evidence_class,
            epoch=epoch,
            reverses_event_id=reverses_event_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            # The withdrawn fact is not copied here. `reverses_event_id` already reaches it, and a
            # second copy would put the same payload — PHI-bearing once C1 clears — in a second row
            # under a different `event_type`, so every masking and retention rule keyed on event
            # type would have to be written twice or miss one.
            payload=Jsonb({"reason": reason}),
        )
        history.append(
            FoldedEvent(
                event_id=event_id,
                to_state="",
                effective_at=effective_at,
                recorded_at=recorded_at,
                reverses_event_id=reverses_event_id,
            )
        )
        folded = _refold_and_write(conn, subject_type, subject_key, history)
        if folded is None:
            raise ReversalLeavesNoStateError(subject_type, subject_key)
        seq = _insert_outbox_row(conn, event_id, subject_type, subject_key)

    return CommitResult(
        event_id=event_id,
        recorded_at=recorded_at,
        rule_version=CATALOG_VERSION,
        outbox_seq=seq,
        state=folded,
    )
