"""Batch entrypoint: read → declare → receipt (task 3.1, spec verdict-relay-run).

`run_relay` drives one relay run: it pages the mart through `MartReader`, hands each validated row
to the `Declarer`, records committed/replayed declarations back into the reader's watermark map,
and commits the durable cursor once per page. The run finishes by emitting a `RunReceipt` with the
seven counts — declared, replayed, skipped-stale, rejected, transitioned, transition-rejected,
failed.

The receipt is structured logs, no new sink (design decision 6): stdlib logging with a JSON
formatter, every record tagged `service:verdict-relay`, and one machine-parsable (Datadog-parsable)
`key=value` summary line carrying the seven counts. Log content is subject keys, verdict types, and
timestamps only — never demographics, never outcome values (no-PHI posture).

Failure semantics (spec: "A run emits a receipt with seven counts"): a row that exhausts the
transient budget, fails validation, or violates the mart contract fails the run — `main` exits
nonzero — with the receipt reflecting the work completed before the failure. The failed page is
*not* committed, so the resumed run re-reads it from the persisted cursor; rows declared before the
crash come back as D16 replays (design risk 4), and correctness never depends on the cursor being
fresh.

Production wiring (constructing the Snowflake `RowSource`, `LedgerCursorStore`, and `service_client`
from configuration) arrives with the scheduler trigger (S1.3); until then callers construct the
reader and declarer and pass them in — which is also what keeps every test socket-free.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from typing import TextIO

from verdict_relay.declarer import Declarer, DeclarerError, RowDisposition
from verdict_relay.mart_reader import MartContractError, MartReader, MartRow

#: The Datadog service tag on every log record and in the summary line.
SERVICE = "verdict-relay"

#: The package logger every module here logs under; `configure_logging` attaches the handler once.
_PACKAGE_LOGGER = "verdict_relay"

logger = logging.getLogger("verdict_relay.run")


class ServiceJsonFormatter(logging.Formatter):
    """One JSON object per line, every record tagged `service:verdict-relay` (design decision 6)."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": SERVICE,
        })


def configure_logging(stream: TextIO | None = None) -> logging.Handler:
    """Attach the service's JSON handler to the package logger and return it for detaching.

    `stream` defaults to stderr; tests pass a `StringIO` to assert on the formatted lines — the
    same lines Datadog parses — rather than on unformatted records.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(ServiceJsonFormatter())
    package_logger = logging.getLogger(_PACKAGE_LOGGER)
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)
    return handler


@dataclass(frozen=True)
class RunReceipt:
    """What one run did: the seven counts, plus the failure detail when the run did not finish."""

    declared: int
    replayed: int
    skipped_stale: int
    rejected: int
    #: Committed paired transitions; a rejected pairing counts under `transition_rejected` instead.
    transitioned: int
    transition_rejected: int
    failed: int
    #: The failing row named by its keys (subject key, verdict type, timestamps) — never content.
    failure: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None

    def summary_line(self) -> str:
        """The single machine-parsable summary line: space-separated `key=value` pairs."""
        result = "success" if self.succeeded else "failure"
        return (
            f"service={SERVICE} result={result} declared={self.declared} replayed={self.replayed} "
            f"skipped_stale={self.skipped_stale} rejected={self.rejected} "
            f"transitioned={self.transitioned} transition_rejected={self.transition_rejected} "
            f"failed={self.failed}"
        )


def _declarer_row(row: MartRow) -> dict[str, object]:
    """The validated row back in contract shape, timestamps ISO — what the declarer names rows by."""
    return {
        "subject_id": row.subject_id,
        "verdict_type": row.verdict_type,
        "outcome": row.outcome,
        "reason": row.reason,
        "rule_version": row.rule_version,
        "as_of": row.as_of.isoformat(),
        "lineage_ref": row.lineage_ref,
        "computed_at": row.computed_at.isoformat(),
    }


def run_relay(reader: MartReader, declarer: Declarer) -> RunReceipt:
    """Read → declare → receipt: one batch run, always ending in the summary line.

    A `DeclarerError` or `MartContractError` ends the run as failed — counted under `failed`,
    named in `RunReceipt.failure` — without committing the failed page, so the resumed run picks
    up from the persisted cursor and D16 answers the recovery overlap as replays.
    """
    failure: str | None = None
    try:
        for batch in reader.batches():
            for row in batch:
                disposition = declarer.declare(_declarer_row(row))
                if disposition in (RowDisposition.DECLARED, RowDisposition.REPLAYED):
                    reader.record_declared(row.subject_id, row.as_of)
            reader.commit()
    except (DeclarerError, MartContractError) as exc:
        failure = str(exc)
        logger.exception("run failed: %s", failure)

    counts = declarer.counts
    receipt = RunReceipt(
        declared=counts.declared,
        replayed=counts.replayed,
        skipped_stale=counts.skipped_stale,
        rejected=counts.rejected,
        transitioned=counts.transitioned,
        transition_rejected=counts.transition_rejected,
        failed=0 if failure is None else 1,
        failure=failure,
    )
    logger.info("%s", receipt.summary_line())
    return receipt


def main(reader: MartReader, declarer: Declarer, *, stream: TextIO | None = None) -> int:
    """Run one batch under the service's JSON logging; zero exit only for a run that finished."""
    handler = configure_logging(stream)
    try:
        receipt = run_relay(reader, declarer)
    finally:
        logging.getLogger(_PACKAGE_LOGGER).removeHandler(handler)
    return 0 if receipt.succeeded else 1
