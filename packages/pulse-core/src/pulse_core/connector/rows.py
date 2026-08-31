"""Inbound read contract — the kit half every connector's reader stands on.

Extracted from the two shipped readers (`consent_ingress.row_source`, `verdict_relay.mart_reader`),
never invented (connector-kit spec: "The kit is extracted, not invented"). Three contracts live
here:

- **`RowSource`** abstracts where inbound rows come from. Every test drives it with
  `FixtureRowSource`; a warehouse adapter is a thin, config-driven implementation. The reader
  never knows which one it holds.
- **Per-row validation** is catch-and-collect: a row that violates its connector's pinned contract
  becomes a counted `RowError` naming the row's page offset and the offending column — **never a
  payload value** — and the run keeps going (`validate_page`, built from `required_string` /
  `required_timestamp`). The no-PHI posture lives in this shape: a `RowError` and a
  `RowValidationError` carry column names and generic detail, nothing from the row itself.
- **The durable cursor** makes a run resumable: `LedgerCursorStore` persists whatever a reader
  checkpoints through the ledger's writer-state facility (`pulse_core.cursor.cursor_path`), scoped
  to the connector's own writer id. A crash between a page's declarations and its cursor save
  re-reads at most that one page, which D16 idempotency classifies as replays downstream —
  correctness never depends on the cursor being fresh.

Each connector keeps what is its own business: the pinned column contract, the validated row type,
and the reader that pages with these primitives.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Protocol, TypeVar, cast

import httpx

from pulse_core.cursor import cursor_path, validate_cursor

RowT = TypeVar("RowT")

DEFAULT_PAGE_SIZE = 500


class RowSource(Protocol):
    """Where inbound rows come from — fixture-backed in every test, the source system in production.

    `fetch` returns raw rows whose cursor column is strictly after `after` (all rows when `after`
    is `None`), ascending by that column, at most `limit` rows — except that a page never splits a
    cursor-column tie: rows sharing the last included value are all included, so paging on a
    strict `>` boundary can never skip a tied row. An empty page means the source is exhausted.
    """

    def fetch(self, *, after: str | None, limit: int) -> Sequence[Mapping[str, object]]: ...


class CursorStore(Protocol):
    """Where a reader's durable cursor lives.

    `load` returns the persisted cursor, or `None` for a writer that has never checkpointed one
    (a first run, not an error). `save` replaces it whole.
    """

    def load(self) -> Mapping[str, object] | None: ...

    def save(self, cursor: Mapping[str, object]) -> None: ...


@dataclass(frozen=True)
class RowError:
    """Why one row failed contract validation.

    Names the row by its page offset and the single offending column — never a payload value, and
    never the row's other contents — the PHI exit this contract owns (connector-kit spec: the
    error names "its position and column", "no payload value is logged").
    """

    row_index: int
    column: str
    detail: str


@dataclass(frozen=True)
class ValidatedPage(Generic[RowT]):
    """One read page split into what validated and what did not.

    A malformed row never displaces a valid one in the same page — `rows` and `errors` are
    independent tallies over the same page, not a filtered/rejected pair.
    """

    rows: list[RowT]
    errors: list[RowError]


class RowValidationError(ValueError):
    """One row's first contract violation, caught by `validate_page` into a `RowError`.

    Carries the offending column separately from the message so the caller never has to parse it
    back out of prose. The detail names the failure kind, never the value that failed.
    """

    def __init__(self, column: str, detail: str) -> None:
        self.column = column
        super().__init__(detail)


def required_string(row: Mapping[str, object], column: str) -> str:
    """The row's `column` as a non-empty string, or `RowValidationError` naming the column."""
    value = row.get(column)
    if not isinstance(value, str) or not value.strip():
        raise RowValidationError(column, f"missing or empty {column!r}")
    return value


def required_timestamp(row: Mapping[str, object], column: str) -> datetime:
    """The row's `column` as a timezone-aware instant, or `RowValidationError` naming the column.

    The detail never carries the offending value — a timestamp column fed from a drifted source
    could hold anything, including payload content.
    """
    value = row.get(column)
    if not isinstance(value, str):
        raise RowValidationError(column, f"{column} is not a string timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RowValidationError(column, f"{column} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RowValidationError(column, f"{column} is timezone-naive")
    return parsed


def validate_page(
    page: Sequence[Mapping[str, object]],
    validator: Callable[[Mapping[str, object]], RowT],
) -> ValidatedPage[RowT]:
    """Catch-and-collect validation over one raw page.

    `validator` turns one raw row into the connector's validated row type, raising
    `RowValidationError` on the row's first contract violation. A malformed row becomes a counted
    `RowError` naming its page offset and offending column, never a payload value; the remaining
    rows in the same page still validate and yield.
    """
    rows: list[RowT] = []
    errors: list[RowError] = []
    for index, row in enumerate(page):
        try:
            rows.append(validator(row))
        except RowValidationError as exc:
            errors.append(RowError(row_index=index, column=exc.column, detail=str(exc)))
    return ValidatedPage(rows=rows, errors=errors)


def parse_instant(row: Mapping[str, object], column: str) -> datetime | None:
    """The row's `column` as a timezone-aware instant, or `None` when it does not parse as one."""
    value = row.get(column)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class FixtureRowSource:
    """A `RowSource` over recorded rows, paging on `cursor_column` — the source every test drives.

    Rows whose cursor column does not parse are always included in the next page rather than
    filtered: hiding them would hide exactly the contract violation the reader must surface, not
    silently page around.
    """

    def __init__(self, rows: Sequence[Mapping[str, object]], *, cursor_column: str) -> None:
        self._rows = list(rows)
        self._cursor_column = cursor_column

    def fetch(self, *, after: str | None, limit: int) -> Sequence[Mapping[str, object]]:
        after_instant = datetime.fromisoformat(after) if after is not None else None
        eligible: list[tuple[datetime | None, Mapping[str, object]]] = []
        for row in self._rows:
            instant = parse_instant(row, self._cursor_column)
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

    `writer_id` is the connector's own writer id — the durable cursor is scoped to it, distinct
    from any D15 command-attribution credential the connector's declarer authenticates with.
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
