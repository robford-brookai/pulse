"""Parse, diff, and declare the D9 consent-reconciliation suppression export (tasks 3.1-3.2).

Three responsibilities, kept separate so 3.3 (the drift receipt) composes on top of this module
rather than duplicating it:

- **`parse_export`** reads the delivered Customer.io suppression export — CSV, fixture-pinned
  format — into `ExportRow`s. A row that fails to parse becomes an `ExportParseError` rather than
  aborting the file (spec: "Malformed rows are counted and attached"); this module only collects
  those errors, the receipt that reports them is 3.3's.
- **`diff_consent`** is the set-based diff (design decision 5): the export's suppression state for
  each (subject, channel) against the ledger's current `communication_consent` state, resolved with
  the export as authority (D9) — Customer.io wins every conflict, per spec.
- **`declare_consent_corrections`** (task 3.2) submits one `record_communication_consent` command
  per `Correction` through the command-API client boundary. Attribution is authentication, never a
  payload field (ADR-0003): the command's actor becomes `reconciliation` because `client`
  authenticates with this sweep's own D15 credential, not because this module writes an actor
  anywhere — `RECONCILIATION_WRITER_ID` documents the credential's name (config; the token value
  comes from the environment at the CLI boundary that constructs `client`). Each command's payload
  carries the export row reference (file id + row number) as provenance, and the D16 idempotency
  key derives from `logical_time` = the export's as-of date, so a re-run of the same export
  replays every correction rather than double-declaring (spec: "A correction is attributed and
  traceable").

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
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

from pulse_core.client import CommandResponse, PulseCoreClient
from pulse_core.generated import RecordCommunicationConsentCommand
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


#: `diff_consent` reads only `subject_type`/`subject_key`/`state` off a `SubjectState` — never
#: `effective_at`/`last_event_id`/`updated_at` — so `load_ledger_state_fixture` fills those with
#: fixed placeholders rather than asking a dry-run fixture to carry fields nothing consumes.
_LEDGER_FIXTURE_PLACEHOLDER_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)
_LEDGER_FIXTURE_PLACEHOLDER_EVENT_ID = uuid.UUID(int=0)


def load_ledger_state_fixture(path: Path) -> list[SubjectState]:
    """Load a `--dry-run` ledger-state substitute: a JSON list of `{subject_key, channel, state}`
    objects at the sweep's own natural (subject, channel) grain — never the composed
    `current_state` row key `diff_consent` looks up internally.

    This is `consent-sweep --dry-run`'s stand-in for a live `enumerate_state` read (task 4.2,
    spec: "Both jobs support an offline dry-run") — omitting `--ledger-fixture` entirely is also
    valid: `diff_consent` against an empty ledger state still derives the full would-declare set
    for a fresh export, just as `opt_out_drift.csv`'s own scenario does.
    """
    rows = json.loads(path.read_text())
    return [
        SubjectState(
            subject_type=SUBJECT_TYPE,
            subject_key=_ledger_key(row["subject_key"], row["channel"]),
            state=row["state"],
            effective_at=_LEDGER_FIXTURE_PLACEHOLDER_TIME,
            last_event_id=_LEDGER_FIXTURE_PLACEHOLDER_EVENT_ID,
            updated_at=_LEDGER_FIXTURE_PLACEHOLDER_TIME,
        )
        for row in rows
    ]


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


#: D15: this sweep's own service credential name. A per-writer bearer credential resolves to
#: `writer_id` = actor server-side (ADR-0003) — so authenticating `client` with the credential
#: named `reconciliation` is what makes every correction's actor `reconciliation`, not any field
#: this module writes. The credential's value (bearer token) lives in the environment and is never
#: hardcoded; only its name is pinned here.
RECONCILIATION_WRITER_ID = "reconciliation"

#: The ledger `to_state` each correction direction declares (catalog: communication_consent
#: transitions) — the mirror image of `_OPTED_OUT_STATE` above.
_TO_STATE: dict[CorrectionDirection, str] = {
    CorrectionDirection.OPT_OUT: "opted_out",
    CorrectionDirection.OPT_IN: "opted_in",
}


def export_row_reference(file_id: str, export_row: ExportRow) -> str:
    """The provenance a correction's payload carries: the export row that produced it (file id +
    row number), so any corrected consent state traces back to the authority that dictated it."""
    return f"{file_id}:row:{export_row.row_number}"


def export_logical_time(export_as_of: date) -> datetime:
    """D16 `logical_time` for sweep corrections: the export's as-of date at midnight UTC.

    No wall-clock component, so every correction derived from the same delivered export derives
    the same idempotency key regardless of what day the sweep happens to run (design decision 3)
    — the same re-runnability month-open's `billing_month_effective_at` gives billing months. A
    next day's export, with its own as-of date, can legitimately re-correct.
    """
    return datetime(export_as_of.year, export_as_of.month, export_as_of.day, tzinfo=timezone.utc)


def build_record_communication_consent_command(
    correction: Correction, *, file_id: str
) -> RecordCommunicationConsentCommand:
    """One `record_communication_consent` correction command, export-attributed."""
    return RecordCommunicationConsentCommand(
        subject_key=_ledger_key(correction.subject_key, correction.channel),
        channel=correction.channel,
        to_state=_TO_STATE[correction.direction],
        evidence_ref=export_row_reference(file_id, correction.export_row),
    )


def dry_run_consent_corrections(
    corrections: Sequence[Correction], *, file_id: str
) -> list[RecordCommunicationConsentCommand]:
    """Build the would-declare set the sweep would submit, without a client at all (task 4.2,
    spec: "Both jobs support an offline dry-run").

    Shares `declare_consent_corrections`'s command-building path — the identical
    `build_record_communication_consent_command` key derivation and provenance — so a dry run
    exercises the real subject-key and payload shape, but never constructs a `PulseCoreClient` or
    calls `submit_command`: no token, no base URL, no socket, ever.
    """
    return [build_record_communication_consent_command(correction, file_id=file_id) for correction in corrections]


@dataclass(frozen=True)
class ConsentCorrectionDeclaration:
    """One correction's command and the client's classified response.

    The drift receipt (task 3.3) is a tally over these; this task returns them uninterpreted.
    """

    correction: Correction
    command: RecordCommunicationConsentCommand
    response: CommandResponse


@dataclass(frozen=True)
class DriftReceipt:
    """One sweep run's drift tally (task 3.3, spec: "The sweep emits a drift receipt and never
    drops rows"): how many export rows agreed with the ledger, how many corrections `diff_consent`
    declared in each direction, and how many rows never parsed.

    Composes over `parse_export`'s and `diff_consent`'s own outputs rather than re-deriving
    anything — this dataclass is a tally, not a second pass over the export. `parse_errors`
    attaches every malformed row's error, not just its count, so a malformed row is never dropped
    without a trace (spec: "Malformed rows are counted and attached"); `ExportParseError` never
    carries a raw contact value — only a row number and a detail about the three tracked columns
    (subject_key, channel, suppressed) — so this receipt is safe to attach whole to logs.
    """

    agreements: int
    opt_out_corrections: int
    opt_in_corrections: int
    unparseable: int
    parse_errors: tuple[ExportParseError, ...]

    @property
    def total_corrections(self) -> int:
        """Corrections declared in either direction — the writes this run actually made."""
        return self.opt_out_corrections + self.opt_in_corrections


def build_drift_receipt(parse_result: ExportParseResult, corrections: Sequence[Correction]) -> DriftReceipt:
    """Tally one sweep run's parse result and diff into its drift receipt.

    `agreements` is every row that parsed but produced no correction (spec: "Agreements produce
    no writes" — `diff_consent` already declares nothing for them; this counts that it didn't, so
    a fully-agreeing export's receipt reports every row as an agreement rather than reporting
    nothing at all). `unparseable` and `parse_errors` are `parse_result.errors` verbatim: rows that
    failed to parse were already counted and collected by `parse_export` without aborting the
    rest, and this receipt attaches that record rather than re-deriving it.
    """
    opt_out_corrections = sum(1 for correction in corrections if correction.direction is CorrectionDirection.OPT_OUT)
    opt_in_corrections = sum(1 for correction in corrections if correction.direction is CorrectionDirection.OPT_IN)
    return DriftReceipt(
        agreements=len(parse_result.rows) - len(corrections),
        opt_out_corrections=opt_out_corrections,
        opt_in_corrections=opt_in_corrections,
        unparseable=len(parse_result.errors),
        parse_errors=tuple(parse_result.errors),
    )


def declare_consent_corrections(
    corrections: Sequence[Correction],
    client: PulseCoreClient,
    *,
    file_id: str,
    export_as_of: date,
) -> list[ConsentCorrectionDeclaration]:
    """Declare one `record_communication_consent` correction per disagreement `diff_consent` found.

    `client` must authenticate with this sweep's own D15 credential (`RECONCILIATION_WRITER_ID`) so
    the ledger resolves the command's actor to `reconciliation` — attribution is authentication
    (ADR-0003), never a payload field this function could set instead. Declarations happen in
    `corrections`' own order — the diff's export-row order.
    """
    effective_at = export_logical_time(export_as_of)
    declarations: list[ConsentCorrectionDeclaration] = []
    for correction in corrections:
        command = build_record_communication_consent_command(correction, file_id=file_id)
        response = client.submit_command(command, effective_at=effective_at)
        declarations.append(ConsentCorrectionDeclaration(correction=correction, command=command, response=response))
    return declarations
