"""Consent landing reader — the ingress's input boundary (design decision 2).

Built on the kit's inbound read contract (`pulse_core.connector`): `RowSource`, catch-and-collect
per-row validation, and the durable cursor through `LedgerCursorStore`. What stays here is this
ingress's own business:

- **The row contract** is pinned: `CONTRACT_COLUMNS` names the five required fields
  (`subject_key`, `channel`, `to_state`, a message/event id, and an orderable event timestamp). A
  row that violates it becomes a counted `RowError` naming the row's page offset and the
  offending column — **never a contact value** — and the run keeps going: this catch-and-collect
  shape is the kit's `validate_page` (corrected at G_MECE — Requirement 5 pins malformed rows as
  counted and attached, never dropped, with the remaining rows in the same page still declared;
  an aborting validator would contradict this change's own spec).
- **The durable cursor** makes a run resumable: the reader pages on the row's event timestamp and
  persists its page position through the ledger's writer-state facility
  (`pulse_core.cursor.cursor_path`), scoped to this ingress's own writer id
  (`CURSOR_WRITER_ID`) — distinct from the `customer-io` D15 credential the declarer (task 3.1)
  authenticates command submission with. A crash between a page's declarations and its `commit()`
  re-reads at most that one page, which D16 idempotency (task 3.2) classifies as a replay
  downstream — correctness never depends on the cursor being fresh.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pulse_core.connector import (
    DEFAULT_PAGE_SIZE,
    CursorStore,
    LedgerCursorStore,
    RowError,
    RowSource,
    ValidatedPage,
    parse_instant,
    required_string,
    required_timestamp,
    validate_page,
)
from pulse_core.connector import FixtureRowSource as _KitFixtureRowSource
from pulse_core.cursor import validate_cursor

__all__ = [
    "CONTRACT_COLUMNS",
    "CURSOR_WRITER_ID",
    "DEFAULT_PAGE_SIZE",
    "ConsentRow",
    "ConsentRowReader",
    "CursorStore",
    "FixtureRowSource",
    "LedgerCursorStore",
    "RowError",
    "RowSource",
    "ValidatedPage",
]

#: The pinned landing row contract (design decision 2; `docs/contracts/consumes.md` once 5.1
#: lands). Order is not significant.
CONTRACT_COLUMNS: tuple[str, ...] = (
    "subject_key",
    "channel",
    "to_state",
    "message_id",
    "event_time",
)

#: Columns that must parse as timezone-aware ISO-8601 timestamps.
_TIMESTAMP_COLUMNS = ("event_time",)

#: Columns that must be non-empty strings once present (every contract column but the timestamp).
_STRING_COLUMNS = tuple(column for column in CONTRACT_COLUMNS if column not in _TIMESTAMP_COLUMNS)

#: The cursor's one page-position key — this reader carries no watermark map, unlike
#: `mart_reader`: D16 idempotency (task 3.2) keys off each row's own event identity, not a
#: per-subject high-water mark the reader would otherwise need to persist.
_CURSOR_PAGE_KEY = "event_time"

#: This ingress's own writer id (design Context) — scopes its durable cursor to itself, never the
#: `customer-io` D15 credential name the declarer (task 3.1) authenticates command submission
#: with.
CURSOR_WRITER_ID = "consent-ingress"


@dataclass(frozen=True)
class ConsentRow:
    """One validated landing row, timestamp parsed, ready for the declarer (task 3.1)."""

    subject_key: str
    channel: str
    to_state: str
    message_id: str
    event_time: datetime


class FixtureRowSource(_KitFixtureRowSource):
    """The kit's fixture source pinned to this reader's cursor column, `event_time` — the source
    every test drives (design decision 6)."""

    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        super().__init__(rows, cursor_column="event_time")


def _validate_row(row: Mapping[str, object]) -> ConsentRow:
    """Validate one raw row against `CONTRACT_COLUMNS`, raising on its first violation.

    Column order matches `CONTRACT_COLUMNS` so a row missing several columns is always named by
    the same one, deterministically, rather than whichever check happens to run first.
    """
    string_fields = {column: required_string(row, column) for column in _STRING_COLUMNS}
    event_time = required_timestamp(row, "event_time")
    return ConsentRow(
        subject_key=string_fields["subject_key"],
        channel=string_fields["channel"],
        to_state=string_fields["to_state"],
        message_id=string_fields["message_id"],
        event_time=event_time,
    )


def _page_boundary(page: Sequence[Mapping[str, object]]) -> str | None:
    """The furthest position `batches()` can safely resume past: the max `event_time` across every
    row in the page that parses one, valid or malformed alike. `None` when no row in the page has
    a parseable `event_time` — the page's only rows are ones the reader must keep re-surfacing.
    """
    instants = [instant for row in page if (instant := parse_instant(row, "event_time")) is not None]
    return max(instants).isoformat() if instants else None


class ConsentRowReader:
    """Pages the consent landing in read order and owns the durable cursor.

    `batches()` yields one `ValidatedPage` at a time. The caller declares the page's valid rows,
    attaches its errors to the run receipt (task 3.3), then calls `commit()` to persist the page
    position — the crash/resume contract this reader shares with `mart_reader`.
    """

    def __init__(self, source: RowSource, cursor_store: CursorStore, *, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        if page_size < 1:
            msg = "page_size must be at least 1"
            raise ValueError(msg)
        self._source = source
        self._store = cursor_store
        self._page_size = page_size
        self._loaded = False
        #: The last *yielded* page's max valid `event_time`; persisted only by `commit()`.
        self._page_event_time: str | None = None

    def _load_cursor(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        cursor = self._store.load()
        if cursor is None:
            return
        page = cursor.get(_CURSOR_PAGE_KEY)
        self._page_event_time = page if isinstance(page, str) else None

    def batches(self) -> Iterator[ValidatedPage[ConsentRow]]:
        """Yield validated pages in read order, resuming from the persisted cursor.

        Cursor advance is computed from every row's *own* `event_time` that parses, valid or
        malformed — not from valid rows alone. A malformed row that fails on some other column
        still occupies a real position in read order once its timestamp is known; excluding it
        from the boundary left it eligible for `RowSource.fetch(after=...)` to re-surface in the
        very next page (whenever a page is not cut short by `limit`, so the malformed row's own,
        later timestamp is never superseded by a valid row's), where it would validate again and
        be double-counted as a second, distinct `RowError` for the same physical row. Only a row
        whose `event_time` itself never parses is excluded from the boundary: the reader has no
        position to advance past for it, so `RowSource.fetch` always re-surfaces it (by contract,
        since hiding it would hide the violation). If a page has no row with a parseable
        `event_time` at all, there is no boundary left to page past, and re-fetching with the same
        `after` would return the same page forever — the reader yields that page's errors once and
        stops rather than loop; the malformed rows are still counted and attached (never silently
        dropped), the run just cannot page past them until the drift is corrected upstream.
        """
        self._load_cursor()
        after = self._page_event_time
        while True:
            raw_page = self._source.fetch(after=after, limit=self._page_size)
            if not raw_page:
                return
            validated = validate_page(raw_page, _validate_row)
            boundary = _page_boundary(raw_page)
            if boundary is None:
                yield validated
                return
            after = boundary
            self._page_event_time = after
            yield validated

    def commit(self) -> None:
        """Persist the page position in one JSON-native save."""
        self._load_cursor()
        cursor: dict[str, object] = {_CURSOR_PAGE_KEY: self._page_event_time}
        self._store.save(validate_cursor(cursor))
