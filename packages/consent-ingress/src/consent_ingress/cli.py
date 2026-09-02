"""`consent_ingress.cli` — one entrypoint, `--dry-run` builds the would-declare set (task 4.1).

`main` parses `argv` and runs the ingress's one job: read the landing through a `RowSource`,
declare every valid row, and print a JSON receipt. There is only one subcommand because there is
only one job (`schedules.cli`'s "one entrypoint" framing, minus the multi-job dispatch it needs and
this package does not).

Both paths share the same reader wiring — `--landing-fixture` names a JSON file of raw landing
rows read into a `FixtureRowSource` — because no production Snowflake adapter exists yet
(`row_source.py`'s own docstring: "the Snowflake adapter over `streamline.cio_raw`/`cio_prod` is a
thin, config-driven implementation added when the warehouse side lands"). `RowSource` is the seam
that adapter drops into; nothing in this module's job functions or wiring changes shape when it
does — the same posture `verdict_relay.run` documents for its own production wiring.

- **`--dry-run`** builds the full would-declare set — one entry per valid row, key derivation and
  payload shape included — and stops before any client is ever constructed: no API call, no
  socket. Malformed rows are counted but never fail a dry run, mirroring
  `schedules.cli`'s consent-sweep dry-run ("with no client to reject a declaration against, a dry
  run has nothing else that can fail").
- **The real run** pages the landing, declares each page's valid rows through a real
  `PulseCoreClient` authenticated with this ingress's own `customer-io` D15 credential, commits the
  cursor after each page, and prints the run receipt (task 3.3). Exit status is nonzero on any
  failed declaration — a response that classifies `rejected`, or a `transient` response that
  exhausted the client's own retry budget (already folded into `RunReceipt.rejected` by
  `build_run_receipt`) — the same scheduler contract precedent `schedules.cli` sets for
  `consent-sweep`. Malformed rows never fail the run on their own (Requirement 5: counted and
  attached, not run-ending); there is no other invariant this ingress enforces.

Receipts print as one JSON object to stdout (`schedules.cli`'s "JSON to stdout" precedent) —
subject keys, channel names, and counts only, per the no-PHI contract `RunReceipt` and
`RowError` already hold to.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TextIO, cast

from pulse_core.client import PulseCoreClient

from consent_ingress.declarer import (
    CUSTOMERIO_WRITER_ID,
    ConsentDeclaration,
    build_record_communication_consent_command,
    build_run_receipt,
    declare_consent_rows,
    log_run_receipt,
)
from consent_ingress.row_source import (
    CURSOR_WRITER_ID,
    DEFAULT_PAGE_SIZE,
    ConsentRow,
    ConsentRowReader,
    CursorStore,
    FixtureRowSource,
    LedgerCursorStore,
    RowError,
    RowSource,
)

#: Environment variables the real run reads production configuration from — only the names are
#: pinned here, per the monorepo's existing convention (`schedules.cli`, `relay_worker.py`).
PULSE_CORE_BASE_URL_ENV_VAR = "PULSE_CORE_BASE_URL"
#: This ingress's own D15 command-attribution credential (`CUSTOMERIO_WRITER_ID`) — authenticates
#: `POST /commands` so the ledger resolves every declared command's actor to `customer-io`.
CUSTOMERIO_TOKEN_ENV_VAR = "CONSENT_INGRESS_CUSTOMERIO_TOKEN"  # noqa: S105 — an env var name, not a secret
#: This ingress's own writer-scoped credential (`CURSOR_WRITER_ID`) — authenticates the durable
#: cursor's `GET/PUT /writers/consent-ingress/cursor`, distinct from the command-attribution
#: credential above (`row_source.CURSOR_WRITER_ID`'s own docstring).
CURSOR_TOKEN_ENV_VAR = "CONSENT_INGRESS_CURSOR_TOKEN"  # noqa: S105 — same, not a secret


class _NullCursorStore:
    """A never-checkpointed `CursorStore` for a dry run: nothing is ever loaded or saved, so a
    dry run never speaks to the ledger's writer-state route either — "no API calls, no sockets"
    means all of them, not only command submission."""

    def load(self) -> Mapping[str, object] | None:
        return None

    def save(self, cursor: Mapping[str, object]) -> None:
        del cursor  # never persisted — a dry run has no position to resume from


def _emit(payload: dict[str, object], *, stream: TextIO) -> None:
    """Print one payload as a single JSON line (`schedules.cli`'s "JSON to stdout" precedent)."""
    print(json.dumps(payload), file=stream)


def _would_declare_entry(row: ConsentRow) -> dict[str, object]:
    """One row's would-be declaration: the exact command a real run would submit, plus the
    `effective_at` its D16 idempotency key would derive from — the same pairing
    `schedules.cli`'s dry-run jobs print."""
    command = build_record_communication_consent_command(row)
    return {"command": command.model_dump(mode="json"), "effective_at": row.event_time.isoformat()}


def dry_run_consent_ingress(
    source: RowSource, *, page_size: int = DEFAULT_PAGE_SIZE
) -> tuple[list[dict[str, object]], list[RowError]]:
    """Build the full would-declare set over every page `source` yields, and the malformed rows
    collected along the way — never constructing a client, so nothing is ever submitted.

    Uses `_NullCursorStore` rather than the durable ledger cursor: a dry run always reads `source`
    from its own beginning and never persists a position, since there is no real run underway to
    resume.
    """
    reader = ConsentRowReader(source, _NullCursorStore(), page_size=page_size)
    would_declare: list[dict[str, object]] = []
    row_errors: list[RowError] = []
    for page in reader.batches():
        would_declare.extend(_would_declare_entry(row) for row in page.rows)
        row_errors.extend(page.errors)
    return would_declare, row_errors


def run_consent_ingress_dry_run_job(
    source: RowSource, *, page_size: int = DEFAULT_PAGE_SIZE, stream: TextIO | None = None
) -> int:
    """Print the would-declare set and always exit zero (task 4.1, spec: dry run exercises key
    derivation and payload shape, stopping before the client — no API calls, no sockets).

    Malformed rows are counted on the payload but never fail a dry run: with no client to reject a
    declaration against, there is nothing else a dry run can fail on (`schedules.cli`'s identical
    consent-sweep dry-run rationale).
    """
    would_declare, row_errors = dry_run_consent_ingress(source, page_size=page_size)
    payload: dict[str, object] = {
        "dry_run": True,
        "would_declare": would_declare,
        "malformed": len(row_errors),
    }
    _emit(payload, stream=stream if stream is not None else sys.stdout)
    return 0


def run_consent_ingress_job(
    source: RowSource,
    client: PulseCoreClient,
    cursor_store: CursorStore,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    stream: TextIO | None = None,
) -> int:
    """Run one full pass over `source`: declare every page's valid rows, commit the cursor after
    each page, print the run receipt, and return the process exit code.

    Exit status is nonzero on any failed declaration — `RunReceipt.rejected` already folds in a
    `rejected` response and a retry-exhausted `transient` one alike (`build_run_receipt`'s own
    three-way split) — the same "the exit status is the contract" posture `schedules.cli` holds
    for `consent-sweep`. Malformed rows never fail the run on their own (Requirement 5).
    """
    reader = ConsentRowReader(source, cursor_store, page_size=page_size)
    declarations: list[ConsentDeclaration] = []
    row_errors: list[RowError] = []
    for page in reader.batches():
        declarations.extend(declare_consent_rows(page.rows, client))
        row_errors.extend(page.errors)
        reader.commit()

    receipt = build_run_receipt(declarations, row_errors)
    log_run_receipt(receipt)
    _emit(cast("dict[str, object]", asdict(receipt)), stream=stream if stream is not None else sys.stdout)
    return 0 if receipt.rejected == 0 else 1


def _load_landing_fixture(path: Path) -> RowSource:
    """The one `RowSource` this CLI wires today: a JSON file of raw landing rows, the identical
    shape `FixtureRowSource` and every test in this package already drive. Swapping in the
    Snowflake adapter over `streamline.cio_raw`/`cio_prod`, once it lands, changes this function
    only — no job function above takes anything but a `RowSource`."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        msg = f"{path}: expected a JSON list of landing rows, got {type(raw).__name__}"
        raise TypeError(msg)
    return FixtureRowSource(cast("Sequence[Mapping[str, object]]", raw))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="consent-ingress",
        description="PULSE Customer.io consent ingress: declare the streamline.cio_raw/cio_prod landing.",
    )
    parser.add_argument(
        "--landing-fixture",
        required=True,
        type=Path,
        help="Path to a JSON list of raw landing rows — this CLI's current RowSource boundary, "
        "read into a FixtureRowSource (task 2.1's shape). Required for both --dry-run and a real "
        "run until the Snowflake adapter lands.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the would-declare set and exit; no ledger connection, no API call, no socket.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Override the reader's page size (tests only).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse `argv`, run the ingress's one job, and return its exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    source = _load_landing_fixture(args.landing_fixture)

    if args.dry_run:
        return run_consent_ingress_dry_run_job(source, page_size=args.page_size)

    base_url = os.environ[PULSE_CORE_BASE_URL_ENV_VAR]
    client = PulseCoreClient(base_url, writer_id=CUSTOMERIO_WRITER_ID, token=os.environ[CUSTOMERIO_TOKEN_ENV_VAR])
    cursor_store = LedgerCursorStore(base_url, writer_id=CURSOR_WRITER_ID, token=os.environ[CURSOR_TOKEN_ENV_VAR])
    return run_consent_ingress_job(source, client, cursor_store, page_size=args.page_size)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
