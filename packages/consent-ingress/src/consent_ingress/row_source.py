"""Consent landing reader — the ingress's input boundary (design decision 2).

Three contracts live here, `verdict_relay.mart_reader`'s shape reused for the parts that carry
over and corrected where the spec disagrees:

- **`RowSource`** abstracts where landing rows come from. Every test drives it with
  `FixtureRowSource`; the Snowflake adapter over `streamline.cio_raw`/`cio_prod` is a thin,
  config-driven implementation added when the warehouse side lands. The reader never knows which
  one it holds.
- **The row contract** is pinned: `CONTRACT_COLUMNS` names the five required fields
  (`subject_key`, `channel`, `to_state`, a message/event id, and an orderable event timestamp). A
  row that violates it becomes a counted `RowError` naming the row's page offset and the
  offending column — **never a contact value** — and the run keeps going: this catch-and-collect
  shape is `consent_sweep.parse_export`'s, not `mart_reader._validated`'s raise-and-abort
  (corrected at G_MECE — Requirement 5 pins malformed rows as counted and attached, never
  dropped, with the remaining rows in the same page still declared; an aborting validator would
  contradict this change's own spec).
- **The durable cursor** makes a run resumable: the reader pages on the row's event timestamp and
  persists its page position through the ledger's writer-state facility
  (`pulse_core.cursor.cursor_path`), scoped to this ingress's own writer id
  (`CURSOR_WRITER_ID`) — distinct from the `customer.io` D15 credential the declarer (task 3.1)
  authenticates command submission with. A crash between a page's declarations and its `commit()`
  re-reads at most that one page, which D16 idempotency (task 3.2) classifies as a replay
  downstream — correctness never depends on the cursor being fresh.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

import httpx
from pulse_core.cursor import cursor_path, validate_cursor

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

DEFAULT_PAGE_SIZE = 500

#: The cursor's one page-position key — this reader carries no watermark map, unlike
#: `mart_reader`: D16 idempotency (task 3.2) keys off each row's own event identity, not a
#: per-subject high-water mark the reader would otherwise need to persist.
_CURSOR_PAGE_KEY = "event_time"

#: This ingress's own writer id (design Context) — scopes its durable cursor to itself, never the
#: `customer.io` D15 credential name the declarer (task 3.1) authenticates command submission
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


@dataclass(frozen=True)
class RowError:
    """Why one row failed contract validation.

    Names the row by its page offset and the single offending column — never a contact value, and
    never the row's other contents — the PHI exit this module owns (spec: "Receipts and logs
    carry no contact values").
    """

    row_index: int
    column: str
    detail: str


@dataclass(frozen=True)
class ValidatedPage:
    """One read page split into what validated and what did not.

    A malformed row never displaces a valid one in the same page (spec: "A malformed row among
    valid ones") — `rows` and `errors` are independent tallies over the same page, not a
    filtered/rejected pair.
    """

    rows: list[ConsentRow]
    errors: list[RowError]


class RowSource(Protocol):
    """Where landing rows come from — fixture-backed in every test, Snowflake in production.

    `fetch` returns raw rows with `event_time` strictly after `after` (all rows when `after` is
    `None`), ascending by `event_time`, at most `limit` rows — except that a page never splits an
    `event_time` tie: rows sharing the last included `event_time` are all included, so paging on a
    strict `>` boundary can never skip a tied row. An empty page means the source is exhausted.
    """

    def fetch(self, *, after: str | None, limit: int) -> Sequence[Mapping[str, object]]: ...


class CursorStore(Protocol):
    """Where the reader's durable cursor lives.

    `load` returns the persisted cursor, or `None` for a writer that has never checkpointed one
    (a first run, not an error). `save` replaces it whole.
    """

    def load(self) -> Mapping[str, object] | None: ...

    def save(self, cursor: Mapping[str, object]) -> None: ...


def _parse_event_time(row: Mapping[str, object]) -> datetime | None:
    value = row.get("event_time")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class FixtureRowSource:
    """A `RowSource` over recorded rows — the source every test drives (design decision 6).

    Rows whose `event_time` does not parse are always included in the next page rather than
    filtered: hiding them would hide exactly the contract violation the reader must count, not
    silently page around.
    """

    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self._rows = list(rows)

    def fetch(self, *, after: str | None, limit: int) -> Sequence[Mapping[str, object]]:
        after_instant = datetime.fromisoformat(after) if after is not None else None
        eligible: list[tuple[datetime | None, Mapping[str, object]]] = []
        for row in self._rows:
            instant = _parse_event_time(row)
            if instant is None:
                eligible.append((None, row))
            elif after_instant is None or instant > after_instant:
                eligible.append((instant, row))
        eligible.sort(key=lambda pair: (pair[0] is not None, pair[0] or datetime.min))

        page: list[Mapping[str, object]] = []
        for instant, row in eligible:
            if len(page) >= limit and instant != eligible[len(page) - 1][0]:
                break
            page.append(row)
        return page


class LedgerCursorStore:
    """The production `CursorStore`: the ledger's `GET/PUT /writers/{writer_id}/cursor`.

    `transport` is the seam tests use (`httpx.MockTransport`) to fake the boundary without a live
    network; production passes none. Auth per D15: the token arrives from configuration (value
    from the environment), and the ledger scopes the cursor to this credential's own writer id.
    """

    def __init__(
        self,
        base_url: str,
        *,
        writer_id: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._path = cursor_path(writer_id)
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def __enter__(self) -> LedgerCursorStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def load(self) -> Mapping[str, object] | None:
        response = self._http.get(self._path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = cast("Mapping[str, object]", response.json())
        cursor = body.get("cursor")
        return validate_cursor(cursor) if cursor is not None else None

    def save(self, cursor: Mapping[str, object]) -> None:
        canonical = validate_cursor(cursor)
        response = self._http.put(self._path, json=canonical)
        response.raise_for_status()


class _RowValidationError(ValueError):
    """Internal: one row's first contract violation, caught by `_validate_row` into a `RowError`.

    Carries the offending column separately from the message so the caller never has to parse it
    back out of prose.
    """

    def __init__(self, column: str, detail: str) -> None:
        self.column = column
        super().__init__(detail)


def _required_string(row: Mapping[str, object], column: str) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value.strip():
        raise _RowValidationError(column, f"missing or empty {column!r}")
    return value


def _required_event_time(row: Mapping[str, object]) -> datetime:
    value = row.get("event_time")
    if not isinstance(value, str):
        raise _RowValidationError("event_time", "event_time is not a string timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _RowValidationError("event_time", f"event_time is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise _RowValidationError("event_time", f"event_time is timezone-naive: {value!r}")
    return parsed


def _validate_row(row: Mapping[str, object]) -> ConsentRow:
    """Validate one raw row against `CONTRACT_COLUMNS`, raising on its first violation.

    Column order matches `CONTRACT_COLUMNS` so a row missing several columns is always named by
    the same one, deterministically, rather than whichever check happens to run first.
    """
    string_fields = {column: _required_string(row, column) for column in _STRING_COLUMNS}
    event_time = _required_event_time(row)
    return ConsentRow(
        subject_key=string_fields["subject_key"],
        channel=string_fields["channel"],
        to_state=string_fields["to_state"],
        message_id=string_fields["message_id"],
        event_time=event_time,
    )


def _validate_page(page: Sequence[Mapping[str, object]]) -> ValidatedPage:
    """Catch-and-collect validation over one raw page (design decision 2, corrected at G_MECE).

    A malformed row becomes a counted `RowError` naming its page offset and offending column,
    never a contact value; the remaining rows in the same page still validate and yield.
    """
    rows: list[ConsentRow] = []
    errors: list[RowError] = []
    for index, row in enumerate(page):
        try:
            rows.append(_validate_row(row))
        except _RowValidationError as exc:
            errors.append(RowError(row_index=index, column=exc.column, detail=str(exc)))
    return ValidatedPage(rows=rows, errors=errors)


def _page_boundary(page: Sequence[Mapping[str, object]]) -> str | None:
    """The furthest position `batches()` can safely resume past: the max `event_time` across every
    row in the page that parses one, valid or malformed alike. `None` when no row in the page has
    a parseable `event_time` — the page's only rows are ones the reader must keep re-surfacing.
    """
    instants = [instant for row in page if (instant := _parse_event_time(row)) is not None]
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

    def batches(self) -> Iterator[ValidatedPage]:
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
            validated = _validate_page(raw_page)
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
