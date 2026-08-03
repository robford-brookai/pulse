"""The outbox relay: committed events to the EventBridge backbone, in per-subject order.

What the distribution spec asks for, and where each part lives:

- **No publish without commit.** The relay only ever reads `ledger.outbox`, and a row is only ever
  in `ledger.outbox` because `commit_declaration`'s transaction put it there. A rolled-back command
  leaves no row, so there is nothing here to publish — the property is structural, not enforced.
- **At-least-once, per-subject sequence order.** A row is marked published *after* the bus accepts
  it, so an ambiguous publish redelivers rather than disappears; consumers dedupe on `event_id`.
  Ordering is head-of-line per subject: a subject's rows go in `seq` order and the first failure
  stops *that subject* for the pass, so `seq` 3 can never overtake a failing `seq` 2. Other
  subjects are untouched by it — cross-subject order is not promised and not preserved.
- **Five attempts, then the DLQ.** Each failure schedules the next attempt with exponential
  backoff; the fifth marks the row dead-lettered with the transport's reason. Dead-lettered rows
  leave the claim index, so one poison row does not block its subject forever *and* does not get
  rescanned forever. Redrive is an operator clearing the marker — never automatic.
- **Lag.** `outbox_lag_seconds` is the age of the oldest row still waiting, which is the quantity
  the p99 < 30 s SLO is stated over. `dead_letter_depth` is what the monitor alarms on at >= 1.

Two relays can run at once. Each subject is guarded by a session-level advisory lock taken in the
two-int namespace, which is a different lock space from the single-bigint one `commit.py` uses —
so the relay serialises against other relays and never against a writer.

`Publisher` is a protocol rather than an import of `EventBridgePublisher`: `ocean-broker` requires
Python 3.13 and this package supports 3.10, and the seam is what lets the ordering and
dead-lettering tests run without boto3 or a bus. `default_publisher` does the real wiring, and asks
for `on_failure="raise"` — the outbox is already this event's durable queue, and letting the
publisher file a second copy in `failed_webhooks` would hide the failure from the policy above.

No PHI reaches a log or the `last_error` column here: log lines carry `event_id`, subject type and
key, and the transport's own message. The envelope — `payload` and `evidence` with it — goes to the
bus and nowhere else.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import groupby
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

#: The EventBridge domain the ledger publishes to — an `ocean_broker.catalog` live domain, so a
#: rule already matches it. Not the envelope's `event_type`, which is per-event.
LEDGER_DOMAIN = "patient-state"

#: Delivery attempts a row gets before it dead-letters (spec: exhausted retries dead-letter loudly).
MAX_ATTEMPTS = 5

#: Backoff for attempt *n* is `INITIAL_BACKOFF_SECONDS * BACKOFF_FACTOR ** (n - 1)`, so a row's five
#: attempts span 1s, 2s, 4s, 8s of waiting — comfortably inside the 30 s lag budget for a subject
#: whose transient failure clears, and fast enough that a poison row alarms in the same minute.
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_FACTOR = 2.0

#: Rows read per pass. Bounds the memory a pass holds and how long a subject's lock is kept; the
#: remainder is simply the next pass's work.
DEFAULT_BATCH_SIZE = 100

#: First argument of the two-int advisory lock, which namespaces relay locks away from every other
#: advisory-lock user in this database. The second is the subject's hash.
_RELAY_LOCK_NAMESPACE = 0x5055_4C53 & 0x7FFFFFFF  # "PULS"

#: Length cap on the stored failure reason. A transport error can be a whole HTTP body; the column
#: is for triage, not for archival.
_MAX_ERROR_CHARS = 1000


class Publisher(Protocol):
    """The publish seam: `ocean_broker.EventBridgePublisher` satisfies it as written."""

    async def publish(self, detail_type: str, event: dict[str, Any], key: str | None = None) -> None:
        """Publish one envelope, raising if the bus refused it."""
        ...


@dataclass(frozen=True)
class PendingRow:
    """One outbox row joined to its event, ready to publish."""

    event_id: uuid.UUID
    subject_type: str
    subject_key: str
    seq: int
    attempts: int
    created_at: datetime
    next_attempt_at: datetime | None
    envelope: dict[str, Any]

    @property
    def subject(self) -> tuple[str, str]:
        return (self.subject_type, self.subject_key)

    @property
    def routing_key(self) -> str:
        """The publisher's grouping key: the subject, which is the grain ordering is promised on."""
        return f"{self.subject_type}/{self.subject_key}"


@dataclass(frozen=True)
class RelayPass:
    """What one pass did, in the terms the relay is monitored by."""

    published: int = 0
    dead_lettered: int = 0
    retried: int = 0
    #: Rows skipped because their subject is inside a backoff window, or its lock was held.
    deferred: int = 0
    #: Age of the oldest published row at the moment it reached the bus — outbox-to-backbone lag.
    max_lag_seconds: float | None = None


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


#: Every envelope field, sourced from the event row. `effective_at` is the ledger's canonical name
#: for business time and `occurred_at` is emitted beside it with the same value — the same alias the
#: write path accepts (commit.py, decision 5), so a consumer written against either name reads the
#: one fact. `seq` and the subject pair travel with the envelope because per-subject ordering is
#: only checkable by a consumer that can see the sequence it is meant to hold.
_SELECT_PENDING_SQL = """
    SELECT o.event_id, o.subject_type, o.subject_key, o.seq, o.attempts, o.created_at,
           o.next_attempt_at,
           e.event_type, e.effective_at, e.recorded_at, e.producer, e.schema_version,
           e.rule_version, e.correlation_id, e.causation_id, e.actor_type, e.actor_id,
           e.actor_authority, e.evidence, e.evidence_class, e.epoch, e.reverses_event_id,
           e.payload
      FROM ledger.outbox o
      JOIN ledger.events e USING (event_id)
     WHERE o.published_at IS NULL AND o.dead_lettered_at IS NULL
     ORDER BY o.subject_type, o.subject_key, o.seq
     LIMIT %(batch_size)s
"""


def _envelope(row: Mapping[str, Any]) -> dict[str, Any]:
    """The published envelope for one outbox row."""
    return {
        "event_id": str(row["event_id"]),
        "event_type": row["event_type"],
        "subject_type": row["subject_type"],
        "subject_key": row["subject_key"],
        "seq": row["seq"],
        "effective_at": row["effective_at"].isoformat(),
        "occurred_at": row["effective_at"].isoformat(),
        "recorded_at": row["recorded_at"].isoformat(),
        "producer": row["producer"],
        "schema_version": row["schema_version"],
        "rule_version": row["rule_version"],
        "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
        "causation_id": str(row["causation_id"]) if row["causation_id"] else None,
        "reverses_event_id": str(row["reverses_event_id"]) if row["reverses_event_id"] else None,
        "actor": {
            "type": row["actor_type"],
            "id": row["actor_id"],
            "authority": row["actor_authority"],
        },
        "evidence": row["evidence"],
        "evidence_class": row["evidence_class"],
        "epoch": row["epoch"],
        "payload": row["payload"],
    }


def pending_rows(conn: psycopg.Connection, *, batch_size: int = DEFAULT_BATCH_SIZE) -> list[PendingRow]:
    """Unpublished, un-dead-lettered rows in per-subject sequence order."""
    cursor = conn.cursor(row_factory=dict_row)
    cursor.execute(_SELECT_PENDING_SQL, {"batch_size": batch_size})
    rows: list[PendingRow] = []
    for values in cursor.fetchall():
        rows.append(
            PendingRow(
                event_id=values["event_id"],
                subject_type=values["subject_type"],
                subject_key=values["subject_key"],
                seq=values["seq"],
                attempts=values["attempts"],
                created_at=values["created_at"],
                next_attempt_at=values["next_attempt_at"],
                envelope=_envelope(values),
            )
        )
    return rows


@contextmanager
def _subject_lock(conn: psycopg.Connection, subject_type: str, subject_key: str) -> Iterator[bool]:
    """Hold this subject against other relays for the block, or yield False if another holds it.

    Session-level, in the two-int namespace: the publish inside the block is a network call, and
    holding a transaction open across it would pin a connection's snapshot for its duration.
    """
    key = f"{subject_type}\x1f{subject_key}"
    acquired: bool = conn.execute(
        "SELECT pg_try_advisory_lock(%s, hashtext(%s))",
        (_RELAY_LOCK_NAMESPACE, key),
    ).fetchone()[0]  # type: ignore[index]
    try:
        yield acquired
    finally:
        if acquired:
            conn.execute("SELECT pg_advisory_unlock(%s, hashtext(%s))", (_RELAY_LOCK_NAMESPACE, key))


def _mark_published(conn: psycopg.Connection, row: PendingRow, published_at: datetime) -> None:
    conn.execute(
        "UPDATE ledger.outbox SET published_at = %(published_at)s, attempts = attempts + 1,"
        "       next_attempt_at = NULL, last_error = NULL"
        " WHERE event_id = %(event_id)s",
        {"published_at": published_at, "event_id": row.event_id},
    )


def _record_failure(conn: psycopg.Connection, row: PendingRow, reason: str, now: datetime) -> bool:
    """Charge one attempt against a row. Returns True when that attempt was its last."""
    attempts = row.attempts + 1
    exhausted = attempts >= MAX_ATTEMPTS
    backoff = INITIAL_BACKOFF_SECONDS * BACKOFF_FACTOR ** (attempts - 1)
    conn.execute(
        "UPDATE ledger.outbox"
        "   SET attempts = %(attempts)s,"
        "       last_error = %(last_error)s,"
        "       next_attempt_at = %(next_attempt_at)s,"
        "       dead_lettered_at = %(dead_lettered_at)s"
        " WHERE event_id = %(event_id)s",
        {
            "attempts": attempts,
            "last_error": reason[:_MAX_ERROR_CHARS],
            "next_attempt_at": None if exhausted else now + timedelta(seconds=backoff),
            "dead_lettered_at": now if exhausted else None,
            "event_id": row.event_id,
        },
    )
    return exhausted


async def _relay_subject(
    conn: psycopg.Connection,
    publisher: Publisher,
    rows: Sequence[PendingRow],
    *,
    domain: str,
    now: datetime,
) -> RelayPass:
    """Publish one subject's rows in `seq` order, stopping at the first failure or backoff."""
    published = dead_lettered = retried = deferred = 0
    max_lag: float | None = None

    for index, row in enumerate(rows):
        if row.next_attempt_at is not None and row.next_attempt_at > now:
            # The head of this subject is still backing off. Everything behind it waits with it:
            # letting a later `seq` past would be exactly the reordering the spec forbids.
            deferred += len(rows) - index
            break
        try:
            await publisher.publish(domain, row.envelope, key=row.routing_key)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if _record_failure(conn, row, reason, now):
                dead_lettered += 1
                # `log.error`, not `log.exception`: a traceback invites an error tracker to
                # capture frame locals, and `row.envelope` is in this frame. The reason string is
                # the transport's; the envelope stays out of the log.
                log.error(  # noqa: TRY400 — see comment
                    "outbox_row_dead_lettered",
                    extra={
                        "event_id": str(row.event_id),
                        "subject_type": row.subject_type,
                        "subject_key": row.subject_key,
                        "seq": row.seq,
                        "attempts": MAX_ATTEMPTS,
                        "reason": reason[:_MAX_ERROR_CHARS],
                    },
                )
                # The poison row has left the claim index, so the rest of this subject is free to
                # go — on the next pass, once this pass's ordering assumption no longer holds.
            else:
                retried += 1
            deferred += len(rows) - index - 1
            break

        publish_time = _now()
        _mark_published(conn, row, publish_time)
        published += 1
        lag = (publish_time - row.created_at).total_seconds()
        max_lag = lag if max_lag is None else max(max_lag, lag)

    return RelayPass(
        published=published,
        dead_lettered=dead_lettered,
        retried=retried,
        deferred=deferred,
        max_lag_seconds=max_lag,
    )


def _merge(left: RelayPass, right: RelayPass) -> RelayPass:
    lags = [lag for lag in (left.max_lag_seconds, right.max_lag_seconds) if lag is not None]
    return RelayPass(
        published=left.published + right.published,
        dead_lettered=left.dead_lettered + right.dead_lettered,
        retried=left.retried + right.retried,
        deferred=left.deferred + right.deferred,
        max_lag_seconds=max(lags) if lags else None,
    )


async def relay_once(
    conn: psycopg.Connection,
    publisher: Publisher,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    domain: str = LEDGER_DOMAIN,
    now: datetime | None = None,
) -> RelayPass:
    """Relay one batch: every eligible subject, each in `seq` order, failures isolated per subject.

    `conn` must be autocommit — each row's outcome is recorded as it happens, so a crash mid-pass
    loses at most the marking of an already-published row, which redelivers and is deduped.
    """
    at = now or _now()
    result = RelayPass()
    for _subject, group in groupby(pending_rows(conn, batch_size=batch_size), key=lambda row: row.subject):
        rows = list(group)
        with _subject_lock(conn, rows[0].subject_type, rows[0].subject_key) as acquired:
            if not acquired:
                # Another relay owns this subject; its rows are that relay's work, not ours.
                result = _merge(result, RelayPass(deferred=len(rows)))
                continue
            result = _merge(result, await _relay_subject(conn, publisher, rows, domain=domain, now=at))
    return result


def dead_letter_depth(conn: psycopg.Connection) -> int:
    """Rows that exhausted their attempts and await a manual redrive. The monitor alarms at >= 1."""
    return int(
        conn.execute("SELECT count(*) FROM ledger.outbox WHERE dead_lettered_at IS NOT NULL").fetchone()[0]  # type: ignore[index]
    )


def outbox_lag_seconds(conn: psycopg.Connection, *, now: datetime | None = None) -> float | None:
    """Age of the oldest row still waiting to reach the bus, or None when the outbox is drained.

    The quantity the p99 < 30 s outbox-to-backbone SLO is stated over. Dead-lettered rows are
    excluded: they are an alarm of their own and would otherwise peg this gauge forever.
    """
    row = conn.execute(
        "SELECT min(created_at) FROM ledger.outbox WHERE published_at IS NULL AND dead_lettered_at IS NULL"
    ).fetchone()
    oldest: datetime | None = row[0] if row else None
    if oldest is None:
        return None
    return ((now or _now()) - oldest).total_seconds()


def redrive(conn: psycopg.Connection, event_id: uuid.UUID) -> bool:
    """Return one dead-lettered row to the relay. The runbook's action, never the relay's.

    Attempts reset to zero: an operator redriving has established that the cause is gone, so the
    row deserves a full budget rather than the one attempt left over from its last failure.
    """
    cursor = conn.execute(
        "UPDATE ledger.outbox SET dead_lettered_at = NULL, next_attempt_at = NULL, attempts = 0"
        " WHERE event_id = %s AND dead_lettered_at IS NOT NULL",
        (event_id,),
    )
    return cursor.rowcount > 0


def default_publisher() -> Publisher:
    """The shared `EventBridgePublisher`, configured for a caller that owns its own queue (D7).

    Imported here rather than at module scope: `ocean-broker` needs Python 3.13 and boto3, and
    neither the relay's logic nor its tests do.
    """
    from ocean_broker import EventBridgePublisher

    return EventBridgePublisher(on_failure="raise")
