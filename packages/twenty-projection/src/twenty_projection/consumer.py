"""The consumer loop: the projection's queue onto the apply core (task 2.3).

`pulse_core.connector.consume` owns the queue mechanics — event-id dedupe, delete-after-success,
malformed-body drop, error backoff — and this module wires it to `handle_event`: a handler
that filters to board-relevant event subjects (a non-board subject is a logged skip, so its
message deletes and never blocks the queue) and otherwise applies with the task-2.2 posture
(orphans park, failed writes retry then surface, at which point the raised error leaves the
message for redelivery).

Credential posture (spec: "The projection holds no ledger credential"): the environment
surface is exactly the Twenty credential and the queue —
`PULSE_TWENTY_<TARGET>_URL` / `PULSE_TWENTY_<TARGET>_TOKEN` (the twenty-deploy convention)
and `SQS_QUEUE_URL`. No ledger DSN, no writer token, no ledger driver import anywhere in this
package: the projection renders state and can never mint or mutate ledger events. A missing
or empty variable fails startup as a `ConsumerStartupError` naming every absent variable.

Log posture: identifiers, states, sequences, and reason codes only — never an event payload
value. Every line built here carries event ids and subject types alone; the apply and
handling layers guarantee the same for theirs.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pulse_core.connector import ConsumerHandler, consume

from twenty_projection.apply import V1_BOARD, BoardTarget, ProjectionRestClient
from twenty_projection.handling import ProjectionMetrics, handle_event

logger = logging.getLogger(__name__)

#: The queue variable every PULSE consumer reads — no bespoke name (OCEAN convention).
QUEUE_URL_VAR = "SQS_QUEUE_URL"


class ConsumerStartupError(Exception):
    """Startup cannot proceed — names every missing environment variable, values never."""


def env_var_names(target: str) -> tuple[str, str]:
    """The Twenty URL and credential variables a target reads — the twenty-deploy convention."""
    return (f"PULSE_TWENTY_{target.upper()}_URL", f"PULSE_TWENTY_{target.upper()}_TOKEN")


@dataclass(frozen=True)
class ConsumerConfig:
    """Everything the consumer holds: one Twenty credential and one queue URL. Nothing else."""

    target: str
    twenty_url: str
    twenty_token: str
    queue_url: str


def resolve_config(target: str, env: Mapping[str, str]) -> ConsumerConfig:
    """Map a target name to the consumer's environment surface, failing by name.

    An empty value counts as missing: an unset secret reaches a job as an empty string, and
    treating that as present would run against nothing.
    """
    url_var, token_var = env_var_names(target)
    missing = [name for name in (url_var, token_var, QUEUE_URL_VAR) if not env.get(name)]
    if missing:
        msg = f"consumer target {target!r} is not configured — set: {', '.join(missing)}"
        raise ConsumerStartupError(msg)
    return ConsumerConfig(
        target=target,
        twenty_url=env[url_var],
        twenty_token=env[token_var],
        queue_url=env[QUEUE_URL_VAR],
    )


def board_handler(
    client: ProjectionRestClient,
    metrics: ProjectionMetrics,
    board: BoardTarget = V1_BOARD,
) -> ConsumerHandler:
    """The per-message handler `pulse_core.consume` drives: filter, then apply.

    A non-board subject returns without applying — the loop then deletes the message, which is
    the point: an irrelevant event must not block the queue or redeliver forever. Everything
    board-relevant goes through `handle_event`, whose raised errors (exhausted writes, data
    faults) propagate so the loop leaves the message for redelivery.
    """

    def handle(envelope: Mapping[str, object]) -> None:
        subject_type = envelope.get("subject_type")
        if subject_type != board.subject_type:
            logger.info(
                "projection skip: event %s subject_type %r is not board-relevant (%r)",
                envelope.get("event_id"),
                subject_type,
                board.subject_type,
            )
            return
        handle_event(envelope, client=client, metrics=metrics, board=board)

    return handle


def run(
    config: ConsumerConfig,
    *,
    client: ProjectionRestClient | None = None,
    sqs_client: Any = None,
    board: BoardTarget = V1_BOARD,
    iterations: int | None = None,
) -> ProjectionMetrics:
    """Consume the queue onto the board — forever, or `iterations` passes for a bounded run.

    `client` and `sqs_client` are the two fixture seams (an `httpx.MockTransport`-backed REST
    client and a fake SQS client); production passes neither and gets the real transports.
    Returns the run's metrics so a bounded run can assert and a caller can emit them.
    """
    metrics = ProjectionMetrics()
    owns_client = client is None
    active_client = client or ProjectionRestClient(config.twenty_url, token=config.twenty_token)
    try:
        consume(
            board_handler(active_client, metrics, board),
            queue_url=config.queue_url,
            sqs_client=sqs_client,
            iterations=iterations,
        )
    finally:
        if owns_client:
            active_client.close()
    return metrics


def main(argv: list[str] | None = None) -> int:
    """`task projection:consume TARGET=<t>`: resolve the environment by name, then loop."""
    parser = argparse.ArgumentParser(
        prog="twenty-projection-consumer",
        description="Consume the projection's ledger queue onto the Twenty board.",
    )
    parser.add_argument("--target", required=True, help="deployment target (dev|staging|prod)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    try:
        config = resolve_config(args.target, os.environ)
    except ConsumerStartupError as error:
        print(f"twenty-projection consumer startup failed: {error}", file=sys.stderr)
        return 2

    logger.info("twenty-projection consumer starting: target %s", config.target)
    run(config)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
