"""`schedules.cli` — one entrypoint, three subcommands (task 4.1, spec: schedule-execution; task
3.1 of billing-state adds `verdict-relay-poll`).

"One CLI exposes every job": `main` parses `argv` into `month-open`, `consent-sweep`, or
`verdict-relay-poll`, runs the named job, and returns the process exit code — the scheduler's own
retry/paging contract keys off that status, never off log content (design decision 6: "the exit
status is the contract"). An unknown subcommand or a missing required argument never reaches a job
at all: argparse's own usage-and-exit(2) behavior handles both (spec: "Subcommands are invocable").
`verdict-relay-poll` (billing-state, spec verdict-relay-trigger) is the schedules-package poll
entry approximating "run after every mart refresh": it wraps the existing verdict-relay's own
`run_relay` rather than reimplementing it, so a poll finding the cursor at the mart's watermark is
already the relay's own no-op-run guarantee (D16 idempotency + the durable cursor + per-subject
stale-skip), not a new invariant this module has to prove.

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
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT, TRANSITION_BY_OUTCOME
from verdict_relay.declarer import Declarer
from verdict_relay.mart_reader import MartReader
from verdict_relay.production import build_production_dependencies, resolve_production_config

from schedules.consent_sweep import (
    RECONCILIATION_WRITER_ID,
    ConsentCorrectionDeclaration,
    build_drift_receipt,
    declare_consent_corrections,
    diff_consent,
    dry_run_consent_corrections,
    export_logical_time,
    load_ledger_state_fixture,
    parse_export,
)
from schedules.consent_sweep import (
    SUBJECT_TYPE as CONSENT_SUBJECT_TYPE,
)
from schedules.month_open import (
    ZERO_ENROLLMENT_INVARIANT,
    EnrollmentSource,
    LedgerEnrollmentSource,
    ZeroEnrollmentError,
    billing_month_effective_at,
    dry_run_month_open,
    load_enrollment_fixture,
    run_month_open,
)
from schedules.verdict_relay_poll import run_verdict_relay_poll_job

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


def run_month_open_dry_run_job(
    source: EnrollmentSource,
    *,
    month: date,
    stream: TextIO | None = None,
) -> int:
    """Build and print month-open's would-declare set; no client, no submission, no socket at all
    (task 4.2, spec: "Both jobs support an offline dry-run").

    Mirrors `run_month_open_job`'s invariant handling without ever constructing a client:
    `ZeroEnrollmentError` becomes the same `invariant_breach` name a real run's receipt carries
    (spec: "Zero enrollments enumerated is a hard failure" applies to a dry run's enumeration
    too) and the process exits nonzero; otherwise every command the real run would submit prints
    alongside the `effective_at` its D16 idempotency key would derive from, and the process exits
    zero (spec: "Dry-run declares nothing" — nothing is ever submitted, dry run or not).
    """
    out = stream if stream is not None else sys.stdout
    try:
        commands = dry_run_month_open(source, month=month)
    except ZeroEnrollmentError:
        _emit({"dry_run": True, "invariant_breach": ZERO_ENROLLMENT_INVARIANT, "would_declare": []}, stream=out)
        return 1
    effective_at = billing_month_effective_at(month).isoformat()
    would_declare = [{"command": command.model_dump(mode="json"), "effective_at": effective_at} for command in commands]
    _emit({"dry_run": True, "invariant_breach": None, "would_declare": would_declare}, stream=out)
    return 0


def run_consent_sweep_dry_run_job(
    csv_text: str,
    ledger_states: Sequence[SubjectState],
    *,
    file_id: str,
    export_as_of: date,
    stream: TextIO | None = None,
) -> int:
    """Build and print the sweep's would-declare set; no client, no submission, no socket at all
    (task 4.2, spec: "Both jobs support an offline dry-run").

    Malformed rows are counted the same way a real run counts them (spec: "Malformed rows are
    counted and attached") but never fail the run — with no client to reject a declaration
    against, a dry run has nothing else that can fail, so this job always exits zero.
    """
    parse_result = parse_export(csv_text)
    corrections = diff_consent(parse_result.rows, ledger_states)
    commands = dry_run_consent_corrections(corrections, file_id=file_id)
    effective_at = export_logical_time(export_as_of).isoformat()
    would_declare = [{"command": command.model_dump(mode="json"), "effective_at": effective_at} for command in commands]
    payload: dict[str, object] = {
        "dry_run": True,
        "would_declare": would_declare,
        "unparseable": len(parse_result.errors),
    }
    _emit(payload, stream=stream if stream is not None else sys.stdout)
    return 0


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


def _verdict_relay_dependencies_from_env() -> tuple[MartReader, Declarer]:
    """The poll's production `MartReader`/`Declarer`, wired from configuration and environment.

    Every environment read happens inside `resolve_production_config` (task 3.1,
    `verdict_relay.production`): a missing variable fails startup naming it, before any Snowflake
    or ledger connection is attempted (spec: "A missing variable fails startup by name"). The
    `Declarer` is seeded from the reader's own persisted watermark map, not a fresh empty one, so a
    resumed poll's stale-skip decisions agree with the cursor it just loaded.
    """
    config = resolve_production_config()
    row_source, cursor_store, client = build_production_dependencies(config)
    reader = MartReader(row_source, cursor_store)
    declarer = Declarer(
        client,
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        transition_by_outcome=TRANSITION_BY_OUTCOME,
        watermarks=reader.watermarks,
    )
    return reader, declarer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schedules",
        description="PULSE clock-driven schedulers: month-open and the D9 consent sweep.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    month_open_parser = subparsers.add_parser("month-open", help="Declare this month's BillingEpisodes.")
    month_open_parser.add_argument(
        "--month",
        type=date.fromisoformat,
        help="Any date (YYYY-MM-DD) within the billing month to open. Required unless --dry-run "
        "supplies one via --fixture.",
    )
    month_open_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the would-declare set and exit; no ledger connection, no API call, no socket.",
    )
    month_open_parser.add_argument(
        "--fixture",
        type=Path,
        help="Path to a recorded enumerate_state fixture (required with --dry-run) — this "
        "package's own JSON shape, e.g. tests/fixtures/normal_month.json.",
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
    consent_sweep_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the would-declare set and exit; no ledger connection, no API call, no socket.",
    )
    consent_sweep_parser.add_argument(
        "--ledger-fixture",
        type=Path,
        default=None,
        help="Path to a ledger consent-state fixture (optional with --dry-run; a JSON list of "
        "{subject_key, channel, state} objects — omitted means no known prior state).",
    )

    subparsers.add_parser(
        "verdict-relay-poll",
        help="Poll the verdict mart and declare committed verdicts (task 3.1, spec "
        "verdict-relay-trigger). Fully env-driven — no arguments beyond the subcommand itself; a "
        "cursor already at the mart's watermark is a no-op run.",
    )

    return parser


def _dispatch_month_open(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """`month-open`'s two paths: `--dry-run --fixture` reads no ledger and touches no client at
    all; otherwise this is task 4.1's original real-wiring path, unchanged."""
    if args.dry_run:
        if args.fixture is None:
            parser.error("month-open --dry-run requires --fixture")
        fixture_month, source = load_enrollment_fixture(args.fixture)
        month = args.month if args.month is not None else fixture_month
        return run_month_open_dry_run_job(source, month=month)
    if args.month is None:
        parser.error("month-open requires --month unless --dry-run is set")
    source = LedgerEnrollmentSource(conn=_ledger_connection_from_env())
    client = _pulse_core_client_from_env(writer_id=MONTH_OPEN_WRITER_ID, token_env_var=MONTH_OPEN_TOKEN_ENV_VAR)
    return run_month_open_job(source, client, month=args.month)


def _dispatch_consent_sweep(args: argparse.Namespace) -> int:
    """`consent-sweep`'s two paths: `--dry-run` reads the export file (never a network call) and
    an optional ledger-state fixture instead of a live ledger; otherwise this is task 4.1's
    original real-wiring path, unchanged. Unlike `_dispatch_month_open`, every consent-sweep
    argument is already unconditionally required at the argparse level, so there is no
    `parser.error` seam here to justify taking `parser` too."""
    csv_text = args.export_file.read_text()
    if args.dry_run:
        ledger_states = load_ledger_state_fixture(args.ledger_fixture) if args.ledger_fixture is not None else []
        return run_consent_sweep_dry_run_job(
            csv_text, ledger_states, file_id=args.file_id, export_as_of=args.export_as_of
        )
    conn = _ledger_connection_from_env()
    ledger_states = enumerate_state(conn, CONSENT_SUBJECT_TYPE)
    client = _pulse_core_client_from_env(writer_id=RECONCILIATION_WRITER_ID, token_env_var=CONSENT_SWEEP_TOKEN_ENV_VAR)
    return run_consent_sweep_job(csv_text, ledger_states, client, file_id=args.file_id, export_as_of=args.export_as_of)


def _dispatch_verdict_relay_poll() -> int:
    """`verdict-relay-poll`'s one path: fully env-driven production wiring, no `--dry-run` (a
    cursor already at the watermark is already a safe no-op — spec: "A no-op poll exits clean")."""
    reader, declarer = _verdict_relay_dependencies_from_env()
    return run_verdict_relay_poll_job(reader, declarer, stream=sys.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse `argv`, run the named job against production wiring, and return its exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "month-open":
        return _dispatch_month_open(args, parser)
    if args.command == "verdict-relay-poll":
        return _dispatch_verdict_relay_poll()

    # Only "month-open", "verdict-relay-poll", and "consent-sweep" are registered subparsers, so
    # `args.command` is one of them by the time argparse's own required-subparser validation has
    # passed.
    return _dispatch_consent_sweep(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
