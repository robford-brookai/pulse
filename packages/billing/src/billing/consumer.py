"""The engine's fact-folding consume loop (task 3.2): `pulse_core.connector.consume` onto
`billing.store.PostgresFactStore`.

`pulse_core.connector.consume` owns the queue mechanics (event-id dedupe, delete-after-success,
malformed-body drop, error backoff — same kit twenty-projection's consumer rides). This module is
exactly the wiring: resolve the two things the engine's fact-folding process needs from its
environment (the `billing_engine` database and its queue), and hand `consume` a handler that folds
every delivered event. Which events the queue delivers is an EventBridge rule concern (design.md
decision 3: "consumes its own SQS queue (rule on `patient-state` and consent domains)"), provisioned
in task 3.5 — this handler has no subject-type filter of its own because the queue's own rule is the
filter, same posture the twenty-projection consumer documents for its own board filter one layer up.

Credential posture (connector-kit spec: "One connector, one credential, no ledger internals"): the
environment surface is exactly the engine's own Postgres credential and the queue —
`BILLING_ENGINE_CREDENTIAL` and `SQS_QUEUE_URL`. No ledger DSN, no ledger driver import anywhere in
this module (`billing_engine` is the engine's own database, never `ledger.*`).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from pulse_core.connector import ConsumerHandler, consume

from billing.store import PostgresFactStore

logger = logging.getLogger(__name__)

#: The queue variable every PULSE consumer reads — no bespoke name (OCEAN convention).
QUEUE_URL_VAR = "SQS_QUEUE_URL"
#: The engine's one connector credential (connector-kit spec: "exactly one writer credential of
#: its own") — a connection string to the engine's own `billing_engine` database, never the
#: ledger's (design.md decision 5).
CREDENTIAL_ENV_VAR = "BILLING_ENGINE_CREDENTIAL"


class ConsumerStartupError(Exception):
    """Startup cannot proceed — names every missing environment variable, values never."""


@dataclass(frozen=True)
class ConsumerConfig:
    """Everything the consumer holds: one Postgres credential and one queue URL. Nothing else."""

    database_url: str
    queue_url: str


def resolve_config(env: Mapping[str, str]) -> ConsumerConfig:
    """Map the environment to the consumer's config, failing by name.

    An empty value counts as missing: an unset secret reaches a job as an empty string, and
    treating that as present would run against nothing.
    """
    missing = [name for name in (CREDENTIAL_ENV_VAR, QUEUE_URL_VAR) if not env.get(name)]
    if missing:
        msg = f"billing-engine consumer is not configured — set: {', '.join(missing)}"
        raise ConsumerStartupError(msg)
    return ConsumerConfig(database_url=env[CREDENTIAL_ENV_VAR], queue_url=env[QUEUE_URL_VAR])


def fold_handler(store: PostgresFactStore) -> ConsumerHandler:
    """The per-message handler `pulse_core.consume` drives: fold, nothing else.

    Every envelope the queue delivers is folded — the queue's own EventBridge rule is what
    scopes delivery to `patient-state` and consent domains, not this handler. `store.apply_event`
    raises on a malformed envelope, which the kit's consume loop leaves for redelivery rather than
    deleting — the same posture twenty-projection's `handle_event` documents for a data fault.
    """

    def handle(envelope: Mapping[str, object]) -> None:
        applied = store.apply_event(envelope)
        logger.info(
            "billing-engine fold: event %s subject %s/%s %s",
            envelope.get("event_id"),
            envelope.get("subject_type"),
            envelope.get("subject_key"),
            "applied" if applied else "skipped (redelivery or out of order)",
        )

    return handle


def run(
    config: ConsumerConfig,
    *,
    conn: psycopg.Connection | None = None,
    sqs_client: Any = None,
    iterations: int | None = None,
) -> None:
    """Consume the queue onto `subject_facts` — forever, or `iterations` passes for a bounded run.

    `conn` and `sqs_client` are the two fixture seams (a Postgres connection and a fake SQS
    client); production passes neither and gets the real transports.
    """
    owns_conn = conn is None
    active_conn = conn or psycopg.connect(config.database_url)
    try:
        consume(
            fold_handler(PostgresFactStore(active_conn)),
            queue_url=config.queue_url,
            sqs_client=sqs_client,
            iterations=iterations,
        )
    finally:
        if owns_conn:
            active_conn.close()


def main(argv: list[str] | None = None) -> int:
    """`task billing:consume`: resolve the environment, then loop."""
    parser = argparse.ArgumentParser(
        prog="billing-engine-consumer",
        description="Fold committed ledger events into billing_engine.subject_facts.",
    )
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    try:
        config = resolve_config(os.environ)
    except ConsumerStartupError as error:
        print(f"billing-engine consumer startup failed: {error}", file=sys.stderr)
        return 2

    logger.info("billing-engine consumer starting")
    run(config)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
