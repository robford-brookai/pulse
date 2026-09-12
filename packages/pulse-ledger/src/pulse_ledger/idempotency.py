"""Idempotent commit — D16, ledger side.

`commit_idempotent` is the write path the command API calls: it claims the client's key in the same
transaction as the event it commits, so the key and the event are durable together or neither is.
A repeat of a claimed key writes nothing and returns the original commit's result with
`replayed=True`, which is what the response classification of decision 6
(`committed | replayed | rejected | transient`) reads.

Two mechanisms, and both are needed:

- **The pre-check** answers the ordinary retry — response lost, writer sends the command again
  minutes later — with one SELECT and no write attempt.
- **The claimed-while-we-tried check** answers the retry that arrives while the original is still in
  flight, which no pre-check can see. The attempt runs inside a savepoint, and if it fails for any
  reason the key is looked up again: a key claimed since the pre-check means the writer's command is
  already committed, so the attempt's failure is irrelevant and the original result is returned. The
  savepoint rollback takes the duplicate event, state write and outbox row with it. Nothing claimed
  means the failure is the writer's answer, and it propagates.

The second check is deliberately not narrowed to the key's unique violation, because a concurrent
duplicate does not reliably surface as one. The per-subject advisory lock `commit_declaration` takes
is held to the end of *this* transaction rather than the savepoint, so the loser waits for the
winner and then folds the winner's event into its own validation — where the same declaration is
usually now an illegal transition (no state in the catalog has a self-loop, so `received -> received`
is refused). Both that rejection and the duplicate-key violation mean the same thing here, and
Postgres has made the winner's row committed and readable by the time either is raised.

A command rejected on its own merits claims no key: nothing is claimed, so the rejection propagates
and the writer's corrected retry can still commit.

`commit_declaration` remains callable on its own — task 3.5's backfill loader and the reversal path
have their own idempotency posture — so "every command carries a key" is enforced at the API
boundary that builds declarations, not here.

## The binding (ADR-0007, amends D16)

A claimed key on its own says *that* some command was answered, never *who* sent it or *what* they
sent: the text before the colon is client-supplied and the digest after it is the SDK's, over a
client-only `logical_time` the server never receives. So a caller that presents a `writer` also
carries a `WriterBinding` — the credential-resolved writer plus the versioned canonical fingerprint
of the accepted request (`pulse_ledger.request_fingerprint`) — and the binding is claimed in the
same savepoint as the event and the key. Three rows or none.

Every replay is then answered from the binding rather than from the key: **both** halves must agree
or the request is refused, including on the race-loser path, where the winner's result is not owed
to whoever else happened to claim the key. A refusal is one `IdempotencyConflictError` for every
mismatch — a different writer and a different request are told apart in the ledger, never in the
response, which would let a caller probe what a key already holds — and it carries no event id, no
result and no fingerprint. Nothing is written by a refusal: the losing attempt's rows go with its
savepoint before the conflict is raised.

`writer` is optional, and that is the rollout's expand stage rather than a permanent alternative
(design decision 5, §Migration Plan). Without one, no binding is written and a claimed key replays
as it did before — the posture the unwired callers still run under. The two directions that would
mix the postures unsafely are both refused: an unbound caller is never answered with a bound key's
result, and a bound caller meeting a key with no binding is answered only from what the original
event proves.

That last case is the migration. `pulse_ledger.legacy_binding` rebuilds the canonical request and
the authenticated writer from the original event's own columns; a key whose event proves all of
both is bound here, in this transaction, and replays, and a key whose event proves less gets
`idempotency_legacy_unverifiable` and keeps its reservation with no binding written. Nothing is
taken from the request in hand — it is compared to the rebuild, never copied into it — so a
mismatch against a rebuilt binding is an ordinary conflict. Mapping these refusals onto HTTP is
task 3.1's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import psycopg

from pulse_ledger.auth import Writer
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration, load_folded_events
from pulse_ledger.fold import FoldedEvent, fold_state
from pulse_ledger.legacy_binding import reconstruct_binding
from pulse_ledger.request_fingerprint import (
    BindingDisposition,
    WriterBinding,
    bind_request,
    classify_binding,
)

#: A key whose binding names another authenticated writer or another canonical request. One reason
#: for both, so the response cannot be used to tell which half mismatched (design decision 3).
IDEMPOTENCY_CONFLICT = "idempotency_conflict"

#: A key claimed before bindings existed, presented by an authenticated writer. Distinct because it
#: is a migration state with a reviewed reconciliation path (design decision 4), not a collision.
IDEMPOTENCY_LEGACY_UNVERIFIABLE = "idempotency_legacy_unverifiable"


class MissingOutboxRowError(LookupError):
    """A claimed key names an event with no outbox row, so its original result is not recoverable.

    The commit path writes the outbox row in the same transaction as the event and nothing in the
    schema removes it, so this is an invariant breach — a relay that prunes published rows would
    cause it, and would need this path revisited rather than a fabricated sequence number.
    """

    def __init__(self, event_id: uuid.UUID) -> None:
        self.event_id = event_id
        super().__init__(f"event {event_id} has no outbox row; its committed sequence cannot be reported")


class IdempotencyConflictError(ValueError):
    """The key is already claimed by a request this one is not a retry of.

    Deliberately says nothing about what the key holds. The message is fixed apart from the reason
    code, and neither the original event id, the writer of record, nor either fingerprint is on the
    exception — a fingerprint is derived from `payload` and `evidence` and is not safe to hand back
    (`pulse_ledger.request_fingerprint`).
    """

    def __init__(self, idempotency_key: str, *, reason: str = IDEMPOTENCY_CONFLICT) -> None:
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(f"idempotency key is claimed by another request ({reason})")


def commit_idempotent(
    conn: psycopg.Connection,
    declaration: Declaration,
    *,
    idempotency_key: str,
    writer: Writer | None = None,
    allow_arbitrary_genesis: bool = False,
) -> CommitResult:
    """Commit one declaration under a client-supplied idempotency key, or replay it.

    Returns the new commit's result, or — if the key was already claimed by this same authenticated
    request — the original commit's result with `replayed=True` and no second event. Raises whatever
    `commit_declaration` raises (`IllegalTransitionError` for a rejected command) without claiming
    the key.

    `writer` is the credential-resolved principal: the bearer `Writer`, the batch route's single
    credential, or `api.WEBHOOK_WRITER` for signed Twenty ingress. Never the key's prefix, which is
    client-supplied text and authenticates nothing (D15). Supplying one binds the key to that writer
    and to the canonical fingerprint of this request, and requires both to match before any later
    replay; omitting one is the pre-enforcement path described in the module docstring.

    Raises `IdempotencyConflictError` when the key is claimed by a request this one is not a retry
    of. Nothing is written when it does.
    """
    binding = (
        bind_request(idempotency_key=idempotency_key, writer=writer, declaration=declaration)
        if writer is not None
        else None
    )
    with conn.transaction():
        already_committed = _settle(conn, idempotency_key, binding)
        if already_committed is not None:
            return already_committed
        try:
            # A savepoint, so a failed attempt discards its own rows without poisoning the
            # transaction the lookup below still has to run in.
            with conn.transaction():
                result = commit_declaration(conn, declaration, allow_arbitrary_genesis=allow_arbitrary_genesis)
                _claim(conn, idempotency_key, result.event_id)
                if binding is not None:
                    _bind(conn, binding, result.event_id)
        except Exception:
            # Broad on purpose: whatever went wrong stops mattering if the key is claimed now — but
            # only by *this* request. `_settle` is the same check the pre-check ran, so the loser of
            # a race re-reads the binding rather than collecting the winner's result, and conflicts
            # if it does not match. Its own rows have already gone with the savepoint.
            winner = _settle(conn, idempotency_key, binding)
            if winner is None:
                raise
            return winner
    return result


def _settle(conn: psycopg.Connection, key: str, binding: WriterBinding | None) -> CommitResult | None:
    """What this request may have from a key already claimed: its result, a conflict, or nothing.

    `None` means the key is unclaimed and the caller should attempt the commit. Every other outcome
    is decided by the binding on record, not by the key's existence — which is the whole of the D16
    amendment, in one place, so the pre-check and the race loser cannot drift into two answers.
    """
    claimed = _claimed_event(conn, key)
    if claimed is None:
        return None
    on_record = _binding_on_record(conn, key)
    if binding is None:
        # No credential presented. A key that carries a binding was claimed by an authenticated
        # writer, and its result is that writer's — the pre-enforcement path may not collect it.
        if on_record is not None:
            raise IdempotencyConflictError(key)
    elif on_record is None:
        # Claimed before bindings existed. `pulse_ledger.legacy_binding` rebuilds one from the
        # original event's own columns, or refuses; nothing is derived from the request in hand,
        # which is only ever compared to what was rebuilt. A key whose event proves nothing keeps
        # its own reason and its reservation — never a guessed binding (ADR-0007, decision 4).
        rebuilt = reconstruct_binding(conn, key, claimed.event_id)
        if rebuilt.binding is None:
            raise IdempotencyConflictError(key, reason=IDEMPOTENCY_LEGACY_UNVERIFIABLE)
        if (
            classify_binding(rebuilt.binding, writer_id=binding.writer_id, fingerprint=binding.fingerprint)
            is BindingDisposition.CONFLICT
        ):
            # A proved binding this request does not match is an ordinary collision, and is refused
            # on the same footing: the key stays with the writer the original event names.
            raise IdempotencyConflictError(key)
        _adopt_legacy(conn, rebuilt.binding, claimed.event_id, binding)
    elif (
        classify_binding(on_record, writer_id=binding.writer_id, fingerprint=binding.fingerprint)
        is BindingDisposition.CONFLICT
    ):
        raise IdempotencyConflictError(key)
    return _replay_of(conn, claimed)


def _claim(conn: psycopg.Connection, key: str, event_id: uuid.UUID) -> None:
    """Reserve the key for the event that satisfied it, for the ledger's lifetime (D16)."""
    conn.execute(
        "INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)",
        (key, event_id),
    )


def _bind(conn: psycopg.Connection, binding: WriterBinding, event_id: uuid.UUID) -> None:
    """Record who claimed the key and what they sent, beside the claim itself (ADR-0007).

    In the same savepoint as the event and the key insert above: the three rows are one claim, and
    a binding that named an event its key did not claim is refused by the composite foreign key
    rather than by an application check (migration 0006).
    """
    conn.execute(
        "INSERT INTO ledger.idempotency_bindings (key, writer_id, fingerprint_version, fingerprint, event_id)"
        " VALUES (%s, %s, %s, %s, %s)",
        (
            binding.idempotency_key,
            binding.writer_id,
            binding.fingerprint_version,
            binding.fingerprint,
            event_id,
        ),
    )


def _adopt_legacy(
    conn: psycopg.Connection, rebuilt: WriterBinding, event_id: uuid.UUID, presented: WriterBinding
) -> None:
    """Record a binding rebuilt from an original event, in the transaction deciding this replay.

    The write is in the same transaction as the answer it justifies, so a failure anywhere after it
    takes the binding with it and the key is simply legacy again — a half-migrated key is not a
    state this path can leave behind.

    One binding per key is the store's rule, so two callers rebuilding the same key concurrently
    race, and the loser's insert violates the primary key rather than finding a row to read. Its own
    savepoint keeps that violation off the outer transaction, and the winner's row is then
    *classified*, not assumed to be equivalent: reconstruction is deterministic from one event, so
    the rows do agree, but a replay that trusted that without checking would be a replay decided by
    an argument rather than by what is stored.
    """
    try:
        with conn.transaction():
            _bind(conn, rebuilt, event_id)
    except psycopg.errors.UniqueViolation:
        winner = _binding_on_record(conn, rebuilt.idempotency_key)
        if (
            classify_binding(winner, writer_id=presented.writer_id, fingerprint=presented.fingerprint)
            is not BindingDisposition.REPLAY
        ):
            raise IdempotencyConflictError(rebuilt.idempotency_key) from None


def _binding_on_record(conn: psycopg.Connection, key: str) -> WriterBinding | None:
    """The authenticated claim stored against `key`, or `None` for a key claimed without one."""
    row = conn.execute(
        "SELECT writer_id, fingerprint, event_id FROM ledger.idempotency_bindings WHERE key = %s",
        (key,),
    ).fetchone()
    if row is None:
        return None
    writer_id, fingerprint, event_id = row
    return WriterBinding(idempotency_key=key, writer_id=writer_id, fingerprint=fingerprint, event_id=event_id)


@dataclass(frozen=True)
class _ClaimedEvent:
    """The committed event a key names, and what a replayed result is rebuilt from."""

    event_id: uuid.UUID
    recorded_at: datetime
    rule_version: str
    subject_type: str
    subject_key: str


def _claimed_event(conn: psycopg.Connection, key: str) -> _ClaimedEvent | None:
    row = conn.execute(
        "SELECT e.event_id, e.recorded_at, e.rule_version, e.subject_type, e.subject_key"
        " FROM ledger.idempotency_keys k JOIN ledger.events e ON e.event_id = k.event_id"
        " WHERE k.key = %s",
        (key,),
    ).fetchone()
    return None if row is None else _ClaimedEvent(*row)


def _replay_of(conn: psycopg.Connection, claimed: _ClaimedEvent) -> CommitResult:
    """The result the commit that claimed the key returned.

    The state is the fold of the subject's history as it stood when that commit returned — not the
    subject's state now. A replay answers the command it repeats, and later events (including a
    reversal of the very event being replayed) are not part of that answer.
    """
    seq = _committed_seq(conn, claimed.event_id)
    return CommitResult(
        event_id=claimed.event_id,
        recorded_at=claimed.recorded_at,
        rule_version=claimed.rule_version,
        outbox_seq=seq,
        state=fold_state(_history_through(conn, claimed.subject_type, claimed.subject_key, seq)),
        replayed=True,
    )


def _history_through(conn: psycopg.Connection, subject_type: str, subject_key: str, seq: int) -> list[FoldedEvent]:
    """The subject's history as of the commit that was assigned outbox `seq`.

    The boundary is the sequence, not `recorded_at`. Per-subject `seq` is assigned under the
    commit's own advisory lock, so it is commit order for this subject and nothing later can be
    inside it — where `recorded_at` is a clock with no uniqueness constraint, and a tie or a
    straggling transaction would otherwise pull a later event into an earlier commit's answer
    (design decision 4: sequence/snapshot evidence, not a wall-clock cutoff).

    `load_folded_events` still decides *which* events are part of a fold, so there is one reading of
    that and not two; this only bounds how far the reading goes.
    """
    committed = {
        row[0]
        for row in conn.execute(
            "SELECT event_id FROM ledger.outbox WHERE subject_type = %s AND subject_key = %s AND seq <= %s",
            (subject_type, subject_key, seq),
        ).fetchall()
    }
    return [event for event in load_folded_events(conn, subject_type, subject_key) if event.event_id in committed]


def _committed_seq(conn: psycopg.Connection, event_id: uuid.UUID) -> int:
    row = conn.execute("SELECT seq FROM ledger.outbox WHERE event_id = %s", (event_id,)).fetchone()
    if row is None:
        raise MissingOutboxRowError(event_id)
    seq: int = row[0]
    return seq
