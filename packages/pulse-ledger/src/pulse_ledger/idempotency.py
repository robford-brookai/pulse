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
"""

from __future__ import annotations

import uuid

import psycopg

from pulse_ledger.commit import CommitResult, Declaration, commit_declaration, load_folded_events
from pulse_ledger.fold import fold_state


class MissingOutboxRowError(LookupError):
    """A claimed key names an event with no outbox row, so its original result is not recoverable.

    The commit path writes the outbox row in the same transaction as the event and nothing in the
    schema removes it, so this is an invariant breach — a relay that prunes published rows would
    cause it, and would need this path revisited rather than a fabricated sequence number.
    """

    def __init__(self, event_id: uuid.UUID) -> None:
        self.event_id = event_id
        super().__init__(f"event {event_id} has no outbox row; its committed sequence cannot be reported")


def commit_idempotent(
    conn: psycopg.Connection,
    declaration: Declaration,
    *,
    idempotency_key: str,
    allow_arbitrary_genesis: bool = False,
) -> CommitResult:
    """Commit one declaration under a client-supplied idempotency key, or replay it.

    Returns the new commit's result, or — if the key was already claimed — the original commit's
    result with `replayed=True` and no second event. Raises whatever `commit_declaration` raises
    (`IllegalTransitionError` for a rejected command) without claiming the key.
    """
    with conn.transaction():
        already_committed = _replay_of(conn, idempotency_key)
        if already_committed is not None:
            return already_committed
        try:
            # A savepoint, so a failed attempt discards its own three rows without poisoning the
            # transaction the lookup below still has to run in.
            with conn.transaction():
                result = commit_declaration(conn, declaration, allow_arbitrary_genesis=allow_arbitrary_genesis)
                _claim(conn, idempotency_key, result.event_id)
        except Exception:
            # Broad on purpose: whatever went wrong stops mattering if the key is claimed now,
            # because then this command is already committed and the writer is owed that result.
            winner = _replay_of(conn, idempotency_key)
            if winner is None:
                raise
            return winner
    return result


def _claim(conn: psycopg.Connection, key: str, event_id: uuid.UUID) -> None:
    """Bind the key to the event that satisfied it, for the ledger's lifetime (D16)."""
    conn.execute(
        "INSERT INTO ledger.idempotency_keys (key, event_id) VALUES (%s, %s)",
        (key, event_id),
    )


def _replay_of(conn: psycopg.Connection, key: str) -> CommitResult | None:
    """The result the commit that claimed `key` returned, or `None` if the key is unclaimed.

    The state is the fold of the subject's history as it stood when that commit returned — not the
    subject's state now. A replay answers the command it repeats, and later events (including a
    reversal of the very event being replayed) are not part of that answer.
    """
    row = conn.execute(
        "SELECT e.event_id, e.recorded_at, e.rule_version, e.subject_type, e.subject_key"
        " FROM ledger.idempotency_keys k JOIN ledger.events e ON e.event_id = k.event_id"
        " WHERE k.key = %s",
        (key,),
    ).fetchone()
    if row is None:
        return None
    event_id, recorded_at, rule_version, subject_type, subject_key = row
    history = [
        event for event in load_folded_events(conn, subject_type, subject_key) if event.recorded_at <= recorded_at
    ]
    return CommitResult(
        event_id=event_id,
        recorded_at=recorded_at,
        rule_version=rule_version,
        outbox_seq=_committed_seq(conn, event_id),
        state=fold_state(history),
        replayed=True,
    )


def _committed_seq(conn: psycopg.Connection, event_id: uuid.UUID) -> int:
    row = conn.execute("SELECT seq FROM ledger.outbox WHERE event_id = %s", (event_id,)).fetchone()
    if row is None:
        raise MissingOutboxRowError(event_id)
    seq: int = row[0]
    return seq
