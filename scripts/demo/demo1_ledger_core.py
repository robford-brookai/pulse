#!/usr/bin/env python
"""Demo 1 — the Phase 1 breakpoint demo for `pulse-ledger-core` (task 5.3).

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints):
a runnable script under `scripts/demo/`, a runbook under `docs/runbooks/`, exits nonzero on any
failed assertion, and stays out of `task check` because it needs LocalStack up. This is the first
demo in the series.

Against the LocalStack + Postgres stack `packages/ocean/infra/docker-compose.yml` already wires
(task 4.5), this shows the four things Demo 1 closes Phase 1 on:

1. A legal command commits and lands on the outbox's queue (the `ledger-relay` compose service
   relays it onto the same bus `event-store` already subscribes to — no new topology).
2. An illegal command rejects with the catalog's reason and version (`IllegalTransitionError`,
   task 3.1).
3. A replay (the same idempotency key twice) returns the original event id, and exactly one event
   is stored (task 3.3).
4. Independently folding a subject's raw committed events equals its co-committed `current_state`
   row after a mixed history (forward, backdated, reversal) — the property task 5.1 proves, wrapped
   here against the real LocalStack-backed stack rather than a throwaway test Postgres.

Talks to `pulse_ledger` directly (not the HTTP command API): `pulse_core.client`'s response
classification does not yet have a wired service to classify against — `_commit_response` does not
echo `replayed` and the API does not accept a client-supplied `idempotency_key` (task 4.3's
HANDOFF.md gap) — so the commit-path functions task 5.1's own harness uses are the faithful way to
demonstrate these properties today.

Usage:
    scripts/demo/demo1_ledger_core.py [--skip-compose-up] [--database-url URL] ...
    scripts/demo/demo1_ledger_core.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from pulse_core.generated import CATALOG_VERSION
from pulse_core.idempotency import derive_idempotency_key
from pulse_ledger.commit import Declaration, commit_declaration, commit_reversal
from pulse_ledger.fold import FoldedEvent, fold_state, state_borne_by
from pulse_ledger.idempotency import commit_idempotent
from pulse_ledger.validation import IllegalTransitionError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE_FILE = REPO_ROOT / "packages" / "ocean" / "infra" / "docker-compose.yml"

#: The compose services this demo needs. Naming `ledger-relay` pulls in its whole dependency chain
#: (`ledger-migrate`, `localstack-init`, and their own dependencies) — `docker compose up` starts a
#: named service's dependencies automatically, so this list does not need to spell those out too.
COMPOSE_SERVICES = ("localstack", "ledger-postgres", "ledger-migrate", "localstack-init", "ledger-relay")

#: Matches the `x-localstack-env` defaults in `packages/ocean/infra/docker-compose.yml`.
DEFAULT_EVENT_BUS_NAME = "ocean"
DEFAULT_AWS_ENDPOINT_URL = "http://localhost:4566"

#: `ledger-postgres`'s host-mapped port and default credentials (docker-compose.yml).
DEFAULT_DATABASE_URL = (
    f"postgresql://ledger:{os.environ.get('LEDGER_POSTGRES_PASSWORD', 'changeme')}@localhost:5434/ledger"
)

#: `event-store` subscribes to every live domain (`ocean_broker.catalog.CONSUMER_DOMAINS`),
#: `patient-state` (the ledger's domain) included — the relayed event lands there with no
#: topology change of its own.
DEFAULT_CONSUMER = "event-store"

WRITER_ID = "demo1-ledger-core"


class DemoAssertionError(AssertionError):
    """One of Demo 1's four assertions failed. The script exits nonzero when this is raised."""


def _check(condition: object, message: str) -> None:
    if not condition:
        raise DemoAssertionError(message)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=DEFAULT_COMPOSE_FILE,
        help=f"docker-compose file to bring the stack up from (default: {DEFAULT_COMPOSE_FILE})",
    )
    parser.add_argument(
        "--skip-compose-up",
        action="store_true",
        help="assume the LocalStack/Postgres stack is already running and skip `docker compose up`",
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="ledger Postgres DSN, a plain postgresql:// URI (psycopg, not SQLAlchemy)",
    )
    parser.add_argument(
        "--aws-endpoint-url",
        default=DEFAULT_AWS_ENDPOINT_URL,
        help=f"LocalStack endpoint (default: {DEFAULT_AWS_ENDPOINT_URL})",
    )
    parser.add_argument(
        "--event-bus-name",
        default=DEFAULT_EVENT_BUS_NAME,
        help=f"bus name the relay publishes to (default: {DEFAULT_EVENT_BUS_NAME})",
    )
    parser.add_argument(
        "--consumer",
        default=DEFAULT_CONSUMER,
        help=f"consumer whose queue the legal command's event is observed on (default: {DEFAULT_CONSUMER})",
    )
    parser.add_argument(
        "--queue-timeout",
        type=float,
        default=30.0,
        help="seconds to wait for the relayed event to reach the consumer queue (default: 30)",
    )
    return parser


def _compose_up(compose_file: Path) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, no interpolated user input
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "--wait", *COMPOSE_SERVICES],  # noqa: S607 - `docker` resolved from PATH
        check=True,
    )


def _sqs_client(endpoint_url: str) -> Any:
    import boto3

    return boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106 - LocalStack's fixed dev credential, not a real secret
    )


def _wait_for_event(sqs: Any, queue_url: str, event_id: uuid.UUID, timeout: float) -> dict[str, Any] | None:
    """Poll the queue until the given event_id shows up in a delivered envelope, or `timeout` passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=5, MaxNumberOfMessages=10)
        for message in response.get("Messages", []):
            body = json.loads(message["Body"])
            detail = body.get("detail", body)
            if detail.get("event_id") == str(event_id):
                return detail
    return None


def _independent_fold(conn: psycopg.Connection, subject_type: str, subject_key: str) -> Any:
    """Re-derive a subject's state from its raw committed rows — mirrors task 5.1's harness."""
    rows = conn.execute(
        "SELECT event_id, payload, effective_at, recorded_at, reverses_event_id"
        " FROM ledger.events WHERE subject_type = %s AND subject_key = %s",
        (subject_type, subject_key),
    ).fetchall()
    events: list[FoldedEvent] = []
    for event_id, payload, effective_at, recorded_at, reverses_event_id in rows:
        to_state = state_borne_by(payload)
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
    return fold_state(events)


def _stored_current_state(conn: psycopg.Connection, subject_type: str, subject_key: str) -> tuple[Any, ...] | None:
    return conn.execute(
        "SELECT state, effective_at, last_event_id FROM ledger.current_state"
        " WHERE subject_type = %s AND subject_key = %s",
        (subject_type, subject_key),
    ).fetchone()


def _declare(subject_key: str, *, event_type: str, to_state: str | None, effective_at: datetime) -> Declaration:
    return Declaration(
        subject_type="referral",
        subject_key=subject_key,
        event_type=event_type,
        to_state=to_state,
        effective_at=effective_at,
        actor_type="system",
        actor_id=WRITER_ID,
        producer="pulse-ledger-demo",
        payload={"note": "demo1_ledger_core"},
    )


def step_legal_commit(conn: psycopg.Connection, sqs: Any, queue_url: str, timeout: float) -> str:
    """1/4: a legal command commits and lands on the queue."""
    subject_key = f"demo1-legal-{uuid.uuid4()}"
    declaration = _declare(subject_key, event_type="referral.received", to_state="received", effective_at=_now())
    result = commit_declaration(conn, declaration)
    _check(result.state is not None, "legal commit produced no current_state")
    _check(result.state.state == "received", f"expected state 'received', got {result.state.state!r}")
    print(f"  committed event {result.event_id} (referral/{subject_key} -> received)")

    detail = _wait_for_event(sqs, queue_url, result.event_id, timeout)
    _check(detail is not None, f"event {result.event_id} never reached queue {queue_url!r} within {timeout}s")
    _check(detail["subject_type"] == "referral", "relayed envelope has the wrong subject_type")
    _check(detail["subject_key"] == subject_key, "relayed envelope has the wrong subject_key")
    print(f"  observed on {queue_url}: event_id={detail['event_id']} subject_key={detail['subject_key']}")
    return subject_key


def step_illegal_commit(conn: psycopg.Connection, subject_key: str) -> None:
    """2/4: an illegal command rejects with the catalog reason + version.

    Reuses the subject `step_legal_commit` left at `received`: `received -> outreach` is not in the
    catalog's adjacency for `referral` (`received` only reaches `closed` or `resolved`).
    """
    declaration = _declare(subject_key, event_type="referral.outreach", to_state="outreach", effective_at=_now())
    try:
        commit_declaration(conn, declaration)
    except IllegalTransitionError as exc:
        _check(bool(exc.reason), "the rejection carried no reason")
        _check(exc.catalog_version == CATALOG_VERSION, "the rejection did not carry the catalog version")
        print(f"  rejected: {exc.reason} (catalog {exc.catalog_version})")
        return
    message = f"referral/{subject_key} 'received' -> 'outreach' committed but should have been illegal"
    raise DemoAssertionError(message)


def step_replay(conn: psycopg.Connection) -> None:
    """3/4: a replay (same idempotency key twice) returns the original event id, exactly one event."""
    subject_key = f"demo1-replay-{uuid.uuid4()}"
    declaration = _declare(subject_key, event_type="referral.received", to_state="received", effective_at=_now())
    key = derive_idempotency_key(
        writer_id=WRITER_ID,
        subject_type=declaration.subject_type,
        subject_key=declaration.subject_key,
        command_type=declaration.event_type,
        payload=declaration.event_payload(),
        logical_time=declaration.effective_at,
    )

    first = commit_idempotent(conn, declaration, idempotency_key=key)
    _check(first.replayed is False, "the first commit was already reported as a replay")

    replay = commit_idempotent(conn, declaration, idempotency_key=key)
    _check(replay.replayed is True, "the repeated command was not classified as a replay")
    _check(replay.event_id == first.event_id, "the replay returned a different event id than the original commit")

    count = conn.execute(
        "SELECT count(*) FROM ledger.events WHERE subject_type = %s AND subject_key = %s",
        ("referral", subject_key),
    ).fetchone()[0]
    _check(count == 1, f"expected exactly one stored event after the replay, found {count}")
    print(f"  original event {first.event_id}; replay returned the same id; {count} event stored")


def step_fold_equivalence(conn: psycopg.Connection) -> None:
    """4/4: the independent fold equals `current_state` after a mixed history (wraps 5.1's harness)."""
    subject_key = f"demo1-fold-{uuid.uuid4()}"
    t0 = _now() - timedelta(days=10)

    commit_declaration(
        conn, _declare(subject_key, event_type="referral.received", to_state="received", effective_at=t0)
    )
    second = commit_declaration(
        conn,
        _declare(subject_key, event_type="referral.resolved", to_state="resolved", effective_at=t0 + timedelta(days=3)),
    )
    commit_declaration(
        conn,
        _declare(subject_key, event_type="referral.closed", to_state="closed", effective_at=t0 + timedelta(days=1)),
    )
    reversal = commit_reversal(
        conn,
        reverses_event_id=second.event_id,
        actor_type="human",
        actor_id="ops-analyst",
        producer="pulse-ledger-demo",
        reason="second_transition_declared_in_error",
    )
    _check(reversal.state is not None, "the reversal left the subject with no state")
    _check(
        reversal.state.state == "closed",
        f"expected the backdated fact ('closed') to resurface after the reversal, got {reversal.state.state!r}",
    )

    stored = _stored_current_state(conn, "referral", subject_key)
    _check(stored is not None, "no current_state row exists after the mixed history")

    folded = _independent_fold(conn, "referral", subject_key)
    _check(folded is not None, "the independent fold produced no state")
    independent = (folded.state, folded.effective_at, folded.event_id)
    _check(independent == stored, f"independent fold {independent!r} != current_state {stored!r}")
    print(f"  independent fold {independent} == current_state (referral/{subject_key})")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    print("=== Demo 1: pulse-ledger-core (Phase 1 breakpoint) ===")
    if args.skip_compose_up:
        print("\n[bring-up] skipped (--skip-compose-up)")
    else:
        print(f"\n[bring-up] docker compose -f {args.compose_file} up -d --wait {' '.join(COMPOSE_SERVICES)}")
        try:
            _compose_up(args.compose_file)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"FAILED: could not bring up the LocalStack/Postgres stack: {exc}", file=sys.stderr)
            return 1

    try:
        sqs = _sqs_client(args.aws_endpoint_url)
        queue_url = sqs.get_queue_url(QueueName=f"{args.event_bus_name}-{args.consumer}")["QueueUrl"]

        with psycopg.connect(args.database_url, autocommit=True) as conn:
            print("\n[1/4] legal command commits and lands on the queue")
            subject_key = step_legal_commit(conn, sqs, queue_url, args.queue_timeout)

            print("\n[2/4] illegal command rejects with catalog reason + version")
            step_illegal_commit(conn, subject_key)

            print("\n[3/4] replay returns the original event id (exactly one event)")
            step_replay(conn)

            print("\n[4/4] independent fold equals current_state (wraps the 5.1 harness)")
            step_fold_equivalence(conn)
    except DemoAssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\n=== Demo 1: all four assertions passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
