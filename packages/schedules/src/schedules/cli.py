"""`schedules.cli` — one entrypoint, two subcommands (task 4.1, spec: schedule-execution).

"One CLI exposes both jobs": `main` parses `argv` into `month-open` or `consent-sweep`, runs the
named job, and returns the process exit code — the scheduler's own retry/paging contract keys off
that status, never off log content (design decision 6: "the exit status is the contract"). An
unknown subcommand or a missing required argument never reaches a job at all: argparse's own
usage-and-exit(2) behavior handles both (spec: "Subcommands are invocable").

Each subcommand's job logic lives in `run_month_open_job` / `run_consent_sweep_job` — plain
functions over the same `EnrollmentSource` / `PulseCoreClient` / `Sequence[SubjectState]`
boundaries `month_open.py` and `consent_sweep.py` already test against, so this module's own tests
drive them the identical way: fakes in, exit code and printed receipt out. `main` is the thin layer
that wires those functions to real argv and real production config (environment variables for
credentials and connection strings, per the monorepo's existing convention — see
`relay_worker.py`, `warehouse_smoke.py`); production wiring itself is exercised by nothing here
since it would need a live ledger and command API, which this package's tests never touch
(design decision 9).

Exit contract for each job:

- **month-open**: `MonthOpenReceipt.ok` is `False` on any failed declaration or the zero-enrollment
  invariant breach (spec: "Zero-enrollment failure", "Receipt reflects the run") — `run_month_open`
  already computes this, so the CLI only reads it.
- **consent-sweep**: the sweep spec makes unparseable rows and agreements explicitly non-fatal
  ("Malformed rows are counted and attached" — the run still succeeds); `build_drift_receipt`
  carries no failure flag of its own because nothing in tasks 3.1-3.3 needed one. This CLI adds the
  one failure mode the spec's generic "exiting nonzero on any failed run" contract implies but the
  receipt does not yet carry: a declared correction whose classified response is `rejected` or
  `transient` — the same "no episode/state actually changed" test month-open's own receipt applies
  to a failed declaration.

Receipts print as one JSON object to stdout (design decision 6: "Receipts are structured (JSON to
stdout)") — subject keys and counts only, per the PHI rule already enforced inside each receipt
dataclass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import TextIO

import psycopg
from pulse_core.client import PulseCoreClient, ResponseClassification
from pulse_ledger.reads import SubjectState, enumerate_state

from schedules.consent_sweep import (
    RECONCILIATION_WRITER_ID,
    ConsentCorrectionDeclaration,
    build_drift_receipt,
    declare_consent_corrections,
    diff_consent,
    parse_export,
)
from schedules.consent_sweep import (
    SUBJECT_TYPE as CONSENT_SUBJECT_TYPE,
)
from schedules.month_open import EnrollmentSource, LedgerEnrollmentSource, run_month_open

#: This job's own D15 credential name (mirrors `consent_sweep.RECONCILIATION_WRITER_ID`) — the
#: writer identity `PulseCoreClient` authenticates as, so the ledger resolves every
#: `open_billing_episode` command's actor to this id (ADR-0003: attribution is authentication).
MONTH_OPEN_WRITER_ID = "schedules-month-open"

#: Environment variables production wiring reads from (never hardcoded, per the monorepo
#: convention — `relay_worker.py`, `warehouse_smoke.py`). Only the names are pinned here; values
#: live in the deploy environment.
DATABASE_URL_ENV_VAR = "DATABASE_URL"
PULSE_CORE_BASE_URL_ENV_VAR = "PULSE_CORE_BASE_URL"
MONTH_OPEN_TOKEN_ENV_VAR = "SCHEDULES_MONTH_OPEN_TOKEN"  # noqa: S105 — an env var name, not a secret
CONSENT_SWEEP_TOKEN_ENV_VAR = "SCHEDULES_RECONCILIATION_TOKEN"  # noqa: S105 — same, not a secret

#: A submitted command's response is a failure for the CLI's exit contract unless it landed as one
#: of these two classifications (mirrors `month_open.build_receipt`'s own test).
_SUCCESSFUL_CLASSIFICATIONS = frozenset({ResponseClassification.COMMITTED, ResponseClassification.REPLAYED})


def _emit(payload: dict[str, object], *, stream: TextIO) -> None:
    """Print one receipt as a single JSON line (design decision 6: "JSON to stdout")."""
    print(json.dumps(payload), file=stream)


def run_month_open_job(
    source: EnrollmentSource,
    client: PulseCoreClient,
    *,
    month: date,
    stream: TextIO | None = None,
) -> int:
    """Run month-open, print its receipt, and return the process exit code.

    `run_month_open` already folds the zero-enrollment invariant breach and any failed declaration
    into `receipt.ok` — this function's only job is to surface that as an exit code. `stream`
    defaults to `None` rather than binding `sys.stdout` at import time — resolved here, at call
    time, so a caller that reassigns `sys.stdout` (pytest's `capsys`, in this package's own tests)
    is honored.
    """
    run = run_month_open(source, client, month=month)
    _emit(asdict(run.receipt), stream=stream if stream is not None else sys.stdout)
    return 0 if run.receipt.ok else 1


def run_consent_sweep_job(
    csv_text: str,
    ledger_states: Sequence[SubjectState],
    client: PulseCoreClient,
    *,
    file_id: str,
    export_as_of: date,
    stream: TextIO | None = None,
) -> int:
    """Parse, diff, declare, and receipt one consent-sweep run; return the process exit code.

    Malformed rows never fail the run (spec: "Malformed rows are counted and attached") — they are
    already counted on `build_drift_receipt`'s `unparseable`. The one failure mode this function
    adds beyond that receipt (module docstring above): any declared correction whose response
    classifies `rejected` or `transient`, named on the printed payload as `failed_declarations` so
    a rejected write is as visible as month-open's `failed_subject_keys` without requiring a
    `consent_sweep.py` shape change task 3.3 never asked for.
    """
    parse_result = parse_export(csv_text)
    corrections = diff_consent(parse_result.rows, ledger_states)
    declarations = declare_consent_corrections(corrections, client, file_id=file_id, export_as_of=export_as_of)
    receipt = build_drift_receipt(parse_result, corrections)
    failed = _failed_correction_subject_keys(declarations)

    payload: dict[str, object] = asdict(receipt)
    payload["failed_declarations"] = len(failed)
    payload["failed_subject_keys"] = failed
    _emit(payload, stream=stream if stream is not None else sys.stdout)
    return 0 if not failed else 1


def _failed_correction_subject_keys(declarations: Sequence[ConsentCorrectionDeclaration]) -> list[str]:
    return [
        declaration.command.subject_key
        for declaration in declarations
        if declaration.response.classification not in _SUCCESSFUL_CLASSIFICATIONS
    ]


def _ledger_connection_from_env() -> psycopg.Connection:
    """The production `EnrollmentSource`'s connection: a live Postgres DSN from the environment,
    never a literal (never the warehouse either — `pulse_ledger.reads.enumerate_state` reads the
    ledger's own co-committed `current_state`, per `month_open.py`'s design decision 9)."""
    return psycopg.connect(os.environ[DATABASE_URL_ENV_VAR])


def _pulse_core_client_from_env(*, writer_id: str, token_env_var: str) -> PulseCoreClient:
    """The production `PulseCoreClient`: base URL and this job's own D15 credential token, both
    from the environment — never `transport=`, so it speaks real HTTP (the seam `PulseCoreClient`
    itself documents: tests pass a fake transport, production wiring passes none)."""
    base_url = os.environ[PULSE_CORE_BASE_URL_ENV_VAR]
    token = os.environ[token_env_var]
    return PulseCoreClient(base_url, writer_id=writer_id, token=token)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schedules",
        description="PULSE clock-driven schedulers: month-open and the D9 consent sweep.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    month_open_parser = subparsers.add_parser("month-open", help="Declare this month's BillingEpisodes.")
    month_open_parser.add_argument(
        "--month",
        required=True,
        type=date.fromisoformat,
        help="Any date (YYYY-MM-DD) within the billing month to open.",
    )

    consent_sweep_parser = subparsers.add_parser("consent-sweep", help="Reconcile the D9 consent export.")
    consent_sweep_parser.add_argument(
        "--export-file",
        required=True,
        type=Path,
        help="Path to the delivered Customer.io suppression export (CSV).",
    )
    consent_sweep_parser.add_argument(
        "--file-id",
        required=True,
        help="This export's id — carried as correction provenance (file id + row number).",
    )
    consent_sweep_parser.add_argument(
        "--export-as-of",
        required=True,
        type=date.fromisoformat,
        help="The export's as-of date (YYYY-MM-DD) — the D16 logical_time for its corrections.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse `argv`, run the named job against production wiring, and return its exit code."""
    args = _build_parser().parse_args(argv)

    if args.command == "month-open":
        source = LedgerEnrollmentSource(conn=_ledger_connection_from_env())
        client = _pulse_core_client_from_env(writer_id=MONTH_OPEN_WRITER_ID, token_env_var=MONTH_OPEN_TOKEN_ENV_VAR)
        return run_month_open_job(source, client, month=args.month)

    # Only "month-open" and "consent-sweep" are registered subparsers, so `args.command` is one
    # of them by the time argparse's own required-subparser validation has passed.
    conn = _ledger_connection_from_env()
    ledger_states = enumerate_state(conn, CONSENT_SUBJECT_TYPE)
    client = _pulse_core_client_from_env(writer_id=RECONCILIATION_WRITER_ID, token_env_var=CONSENT_SWEEP_TOKEN_ENV_VAR)
    csv_text = args.export_file.read_text()
    return run_consent_sweep_job(csv_text, ledger_states, client, file_id=args.file_id, export_as_of=args.export_as_of)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
