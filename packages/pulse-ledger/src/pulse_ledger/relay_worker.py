"""Standalone relay loop for the `ledger-relay` compose service (task 4.5).

`relay_fair_pass` (relay.py) is one fairness-scheduled pass — bounded candidate-subject scanning
plus a per-subject row budget (relay-fairness 1.2) — and a running service just repeats it, holding
the `ScanState` it returns so scan progress survives across passes rather than restarting at the
front of the candidate set every time. `DATABASE_URL` (a plain `postgresql://` DSN —
`psycopg.connect` does not understand the `+driver` suffix SQLAlchemy uses) and the bus environment
(`AWS_ENDPOINT_URL` et al., `default_publisher`'s concern) both come from the compose service's own
environment.

Run as `python -m pulse_ledger.relay_worker`.
"""

from __future__ import annotations

import asyncio
import logging
import os

import psycopg

from pulse_ledger.relay import ScanState, default_publisher, relay_fair_pass

log = logging.getLogger(__name__)

#: Seconds between passes. A pass with nothing pending is cheap (one indexed SELECT), so a short
#: default keeps outbox lag low without a queueing mechanism of its own.
POLL_INTERVAL_SECONDS = float(os.environ.get("RELAY_POLL_INTERVAL_SECONDS", "1"))


async def run_forever(database_url: str) -> None:
    """Relay passes, forever, one at a time — the shape a supervised container process wants."""
    publisher = default_publisher()
    state = ScanState()
    with psycopg.connect(database_url, autocommit=True) as conn:
        while True:
            result, state = await relay_fair_pass(conn, publisher, state)
            if result.published or result.dead_lettered:
                # max_lag_seconds is the ADR-0004 D17 gauge (p99 outbox-to-backbone < 30 s);
                # the deployment's log stream is the only place an operator can read it.
                log.info(
                    "relay_pass",
                    extra={
                        "published": result.published,
                        "dead_lettered": result.dead_lettered,
                        "max_lag_seconds": result.max_lag_seconds,
                    },
                )
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever(os.environ["DATABASE_URL"]))


if __name__ == "__main__":  # pragma: no cover
    main()
