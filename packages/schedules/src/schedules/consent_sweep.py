"""Parse and diff the D9 consent-reconciliation suppression export (task 3.1).

Two responsibilities, kept separate so 3.2 (attribution/provenance) and 3.3 (the drift receipt)
compose on top of this module rather than duplicating it:

- **`parse_export`** reads the delivered Customer.io suppression export — CSV, fixture-pinned
  format — into `ExportRow`s. A row that fails to parse becomes an `ExportParseError` rather than
  aborting the file (spec: "Malformed rows are counted and attached"); this module only collects
  those errors, the receipt that reports them is 3.3's.
- **`diff_consent`** is the set-based diff (design decision 5): the export's suppression state for
  each (subject, channel) against the ledger's current `communication_consent` state, resolved with
  the export as authority (D9) — Customer.io wins every conflict, per spec.

The export's grain is (subject, channel) — one patient can appear once per channel (SMS, email,
voice), per the object model (`CommunicationConsent` — per patient x channel). The ledger's
`current_state` table carries one row per `(subject_type, subject_key)`, a single string, so this
module composes that string as `f"{subject_key}:{channel}"` to look a (subject, channel) pair up in
the states `enumerate_state` returns — the compound grain design decision 5 describes, made
concrete. `enumerate_state` is expected to have already scoped its query to
`subject_type="communication_consent"`; the diff filters by it again rather than trust the caller,
since a stray row of another subject type could otherwise collide on the same composed key string.

No PHI in row errors or corrections: subject keys and channel names only, never contact values.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from pulse_ledger.reads import SubjectState

#: The one subject type this sweep reconciles (catalog: `state_catalog_seed.yaml`).
SUBJECT_TYPE = "communication_consent"

#: The ledger's recorded state meaning "Customer.io suppresses this channel" (catalog:
#: communication_consent transitions). Absence of a current-state row — the catalog's implicit
#: `unset` — is treated the same as any non-`opted_out` state: not suppressed.
_OPTED_OUT_STATE = "opted_out"

#: Fixture-pinned export columns (design decision 5). Order is not significant; `csv.DictReader`
#: matches by header name.
REQUIRED_COLUMNS: tuple[str, ...] = ("subject_key", "channel", "suppressed")

_TRUE_VALUES = frozenset({"true", "1", "yes"})
_FALSE_VALUES = frozenset({"false", "0", "no"})


class ExportHeaderError(ValueError):
    """The export's header is missing a required column — every row would fail alike.

    Raised once, before any row is read, rather than as `len(REQUIRED_COLUMNS)` identical
    per-row errors.
    """

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        super().__init__(f"suppression export missing required column(s): {', '.join(self.missing)}")


@dataclass(frozen=True)
class ExportRow:
    """One parsed suppression-export row — the unit of provenance 3.2's corrections carry."""

    row_number: int
    subject_key: str
    channel: str
    suppressed: bool


@dataclass(frozen=True)
class ExportParseError:
    """Why one row failed to parse. Never carries the raw row — it may hold contact values."""

    row_number: int
    detail: str


@dataclass(frozen=True)
class ExportParseResult:
    """Every row this export produced, split into what parsed and what did not.

    Rows and errors both index from 1 in file order (the header is row 0, never referenced) —
    the ordinary spreadsheet convention, and what a triage runbook can act on directly.
    """

    rows: list[ExportRow]
    errors: list[ExportParseError]


class _RowError(ValueError):
    """Internal: a single row's parse failure, caught by `parse_export` into `ExportParseError`."""


def _required_field(raw: dict[str, str | None], column: str) -> str:
    value = raw.get(column)
    if value is None or not value.strip():
        msg = f"missing or empty {column!r}"
        raise _RowError(msg)
    return value.strip()


def _parse_suppressed(value: str | None) -> bool:
    if value is None:
        msg = "missing 'suppressed'"
        raise _RowError(msg)
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    msg = f"'suppressed' is not a recognised boolean: {value!r}"
    raise _RowError(msg)


def _parse_row(row_number: int, raw: dict[str, str | None]) -> ExportRow:
    subject_key = _required_field(raw, "subject_key")
    channel = _required_field(raw, "channel")
    suppressed = _parse_suppressed(raw.get("suppressed"))
    return ExportRow(row_number=row_number, subject_key=subject_key, channel=channel, suppressed=suppressed)


def parse_export(csv_text: str) -> ExportParseResult:
    """Parse the delivered suppression export into rows and per-row parse errors.

    Raises `ExportHeaderError` if a required column is absent from the header — a structural
    problem no row-level accounting can repair. A malformed individual row never aborts the rest
    (spec: "Malformed rows are counted and attached").
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or ())]
    if missing:
        raise ExportHeaderError(missing)

    rows: list[ExportRow] = []
    errors: list[ExportParseError] = []
    for row_number, raw in enumerate(reader, start=1):
        try:
            rows.append(_parse_row(row_number, raw))
        except _RowError as exc:
            errors.append(ExportParseError(row_number=row_number, detail=str(exc)))
    return ExportParseResult(rows=rows, errors=errors)


class CorrectionDirection(str, Enum):
    """Which way a correction moves the ledger's recorded state — export is always the reason."""

    OPT_OUT = "opt_out"
    OPT_IN = "opt_in"


@dataclass(frozen=True)
class Correction:
    """One (subject, channel) disagreement, export-authoritative (D9).

    `export_row` is the provenance 3.2's `record_communication_consent` payload references (file
    id + row number) — carried here so the declarer never re-reads the export to attribute a
    correction it already computed.
    """

    subject_key: str
    channel: str
    direction: CorrectionDirection
    export_row: ExportRow


def _ledger_key(subject_key: str, channel: str) -> str:
    """The `current_state` row key for one (subject, channel) `communication_consent` grain."""
    return f"{subject_key}:{channel}"


def diff_consent(export_rows: Sequence[ExportRow], ledger_states: Sequence[SubjectState]) -> list[Correction]:
    """The export's suppression set against the ledger's current consent state, export-wins.

    - export suppressed, ledger not already `opted_out` → `opt_out` correction (spec: "Opt-out
      missing from the ledger").
    - export not suppressed, ledger `opted_out` → `opt_in` correction (spec: "Ledger opt-out the
      export contradicts").
    - Otherwise, agreement: no correction (spec: "Agreements produce no writes").
    """
    ledger_index = {state.subject_key: state.state for state in ledger_states if state.subject_type == SUBJECT_TYPE}
    corrections: list[Correction] = []
    for row in export_rows:
        is_opted_out = ledger_index.get(_ledger_key(row.subject_key, row.channel)) == _OPTED_OUT_STATE
        if row.suppressed and not is_opted_out:
            direction = CorrectionDirection.OPT_OUT
        elif not row.suppressed and is_opted_out:
            direction = CorrectionDirection.OPT_IN
        else:
            continue
        corrections.append(
            Correction(subject_key=row.subject_key, channel=row.channel, direction=direction, export_row=row)
        )
    return corrections
