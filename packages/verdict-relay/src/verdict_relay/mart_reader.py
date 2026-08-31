"""Verdict mart reader — the relay's input boundary (design decisions 2 and 3).

Built on the kit's inbound read contract (`pulse_core.connector`): `RowSource`, `CursorStore`,
the fixture source, and the durable cursor through `LedgerCursorStore`. What stays here is this
relay's own business:

- **The row contract** is pinned: one row per (subject, verdict_type, run), the eight columns in
  `CONTRACT_COLUMNS`, timestamps ISO-8601 and timezone-aware. A row that violates it fails the run
  with `MartContractError` naming the row, before any row of its page is yielded — drift in the
  warehouse mart surfaces here, not as a half-declared batch.
- **The durable cursor** makes a run resumable: the reader pages on `computed_at` and persists its
  page position together with the per-subject `as_of` watermark map in one save, through the
  ledger's writer-state facility (`pulse_core.cursor.cursor_path`), JSON-native per
  `validate_cursor`. A crash between a page's declarations and its `commit()` re-reads at most that
  one page, which D16 idempotency classifies as replays downstream — correctness never depends on
  the cursor being fresh.

The watermark map is written by whoever declares (the run entrypoint calls `record_declared`
after a committed or replayed declaration) and read back on resume; the reader only carries and
persists it, updated-only-forward.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from pulse_core.connector import DEFAULT_PAGE_SIZE, CursorStore, LedgerCursorStore, RowSource
from pulse_core.connector import FixtureRowSource as _KitFixtureRowSource
from pulse_core.cursor import validate_cursor

__all__ = [
    "CONTRACT_COLUMNS",
    "DEFAULT_PAGE_SIZE",
    "CursorStore",
    "FixtureRowSource",
    "LedgerCursorStore",
    "MartContractError",
    "MartReader",
    "MartRow",
    "RowSource",
]

#: The pinned mart row contract (design Context; `docs/contracts/consumes.md` once 5.2 lands).
CONTRACT_COLUMNS: tuple[str, ...] = (
    "subject_id",
    "verdict_type",
    "outcome",
    "reason",
    "rule_version",
    "as_of",
    "lineage_ref",
    "computed_at",
)

#: Columns that must parse as timezone-aware ISO-8601 timestamps.
_TIMESTAMP_COLUMNS = ("as_of", "computed_at")

#: Cursor keys — one JSON document carries both resume points (design decision 3).
_CURSOR_PAGE_KEY = "computed_at"
_CURSOR_WATERMARKS_KEY = "watermarks"


class MartContractError(RuntimeError):
    """A mart row violates the pinned contract; the run fails naming the row.

    The name is built from the row's identifying keys (subject key, verdict type, `computed_at`) —
    subject keys only, never demographic fields, per the no-PHI posture.
    """

    def __init__(self, row_name: str, problem: str) -> None:
        self.row_name = row_name
        self.problem = problem
        super().__init__(f"mart row {row_name}: {problem}")


@dataclass(frozen=True)
class MartRow:
    """One validated mart row, timestamps parsed, ready for the declarer."""

    subject_id: str
    verdict_type: str
    outcome: str
    reason: str | None
    rule_version: str
    as_of: datetime
    lineage_ref: str
    computed_at: datetime


class FixtureRowSource(_KitFixtureRowSource):
    """The kit's fixture source pinned to this reader's cursor column, `computed_at` — the
    test-side implementation (design decision 2)."""

    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        super().__init__(rows, cursor_column="computed_at")


def _name_row(index: int, row: Mapping[str, object]) -> str:
    """Identify a row for an error message: page index plus whatever identifying keys it carries."""
    keys: list[str] = []
    for column in ("subject_id", "verdict_type", "computed_at"):
        value = row.get(column)
        if isinstance(value, str):
            keys.append(f"{column}={value}")
    detail = ", ".join(keys) if keys else "no identifying columns present"
    return f"[page offset {index}] ({detail})"


def _validated(index: int, row: Mapping[str, object]) -> MartRow:
    missing = [column for column in CONTRACT_COLUMNS if column not in row]
    if missing:
        raise MartContractError(_name_row(index, row), f"missing contract column(s): {', '.join(missing)}")

    instants: dict[str, datetime] = {}
    for column in _TIMESTAMP_COLUMNS:
        value = row[column]
        if not isinstance(value, str):
            raise MartContractError(_name_row(index, row), f"{column} is not a string timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise MartContractError(_name_row(index, row), f"{column} is not ISO-8601: {value!r}") from exc
        if parsed.tzinfo is None:
            raise MartContractError(_name_row(index, row), f"{column} is timezone-naive: {value!r}")
        instants[column] = parsed

    reason = row["reason"]
    string_fields: dict[str, str] = {}
    for column in ("subject_id", "verdict_type", "outcome", "rule_version", "lineage_ref"):
        value = row[column]
        if not isinstance(value, str):
            raise MartContractError(_name_row(index, row), f"{column} is not a string")
        string_fields[column] = value
    if reason is not None and not isinstance(reason, str):
        raise MartContractError(_name_row(index, row), "reason is neither a string nor null")

    return MartRow(
        subject_id=string_fields["subject_id"],
        verdict_type=string_fields["verdict_type"],
        outcome=string_fields["outcome"],
        reason=reason,
        rule_version=string_fields["rule_version"],
        as_of=instants["as_of"],
        lineage_ref=string_fields["lineage_ref"],
        computed_at=instants["computed_at"],
    )


class MartReader:
    """Pages the mart in declaration order and owns the durable cursor.

    `batches()` yields one validated page at a time, each sorted (subject, `as_of`) so the declarer
    receives every subject's verdicts oldest first. The caller declares a batch, records each
    committed/replayed declaration via `record_declared`, then calls `commit()` to persist the page
    position and the watermark map in one save — the crash/resume contract of the verdict-mart-read
    spec.
    """

    def __init__(self, source: RowSource, cursor_store: CursorStore, *, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        if page_size < 1:
            msg = "page_size must be at least 1"
            raise ValueError(msg)
        self._source = source
        self._store = cursor_store
        self._page_size = page_size
        self._loaded = False
        #: The last *yielded* page's max `computed_at`; persisted only by `commit()`.
        self._page_computed_at: str | None = None
        self._watermarks: dict[str, str] = {}

    def _load_cursor(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        cursor = self._store.load()
        if cursor is None:
            return
        page = cursor.get(_CURSOR_PAGE_KEY)
        self._page_computed_at = page if isinstance(page, str) else None
        watermarks = cursor.get(_CURSOR_WATERMARKS_KEY)
        if isinstance(watermarks, Mapping):
            items = cast("Mapping[object, object]", watermarks).items()
            self._watermarks = {
                subject: as_of for subject, as_of in items if isinstance(subject, str) and isinstance(as_of, str)
            }

    def watermark(self, subject_id: str) -> datetime | None:
        """The subject's latest declared `as_of`, or `None` if it has never been declared."""
        self._load_cursor()
        value = self._watermarks.get(subject_id)
        return datetime.fromisoformat(value) if value is not None else None

    @property
    def watermarks(self) -> dict[str, str]:
        """Every subject's persisted high-water `as_of`, loaded from the durable cursor.

        Production wiring (task 3.1) seeds the `Declarer`'s own watermark map from this, so both
        halves of a resumed run start from the identical persisted state rather than the reader
        and declarer disagreeing about what was already declared.
        """
        self._load_cursor()
        return dict(self._watermarks)

    def record_declared(self, subject_id: str, as_of: datetime) -> None:
        """Raise the subject's watermark after a committed or replayed declaration.

        Update-only-forward: an older `as_of` never regresses the watermark, so a replayed
        boundary overlap after a crash cannot roll stale detection backwards.
        """
        self._load_cursor()
        current = self._watermarks.get(subject_id)
        if current is None or datetime.fromisoformat(current) < as_of:
            self._watermarks[subject_id] = as_of.isoformat()

    def batches(self) -> Iterator[list[MartRow]]:
        """Yield validated pages in declaration order, resuming from the persisted cursor."""
        self._load_cursor()
        after = self._page_computed_at
        while True:
            raw_page = self._source.fetch(after=after, limit=self._page_size)
            if not raw_page:
                return
            validated = [_validated(index, row) for index, row in enumerate(raw_page)]
            validated.sort(key=lambda row: (row.subject_id, row.as_of))
            after = max(row.computed_at for row in validated).isoformat()
            self._page_computed_at = after
            yield validated

    def commit(self) -> None:
        """Persist the page position and the watermark map in one JSON-native save."""
        self._load_cursor()
        cursor: dict[str, object] = {
            _CURSOR_PAGE_KEY: self._page_computed_at,
            _CURSOR_WATERMARKS_KEY: dict(self._watermarks),
        }
        self._store.save(validate_cursor(cursor))
