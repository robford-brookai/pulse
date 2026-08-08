"""`consent_ingress.row_source` — pinned contract, catch-and-collect validation, cursor paging.

Covers the every-Snowflake-read-is-fixture-faked and malformed-row-among-valid-ones scenarios.
All rows are synthetic; the cursor endpoint is faked at the httpx boundary
(`httpx.MockTransport`), never mocked driver internals. No test opens a socket — enforced by
`tests/conftest.py`, verified directly here too.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx
import pytest
from consent_ingress.row_source import (
    CONTRACT_COLUMNS,
    ConsentRow,
    ConsentRowReader,
    FixtureRowSource,
    LedgerCursorStore,
    RowError,
)
from pulse_core.cursor import cursor_path, validate_cursor
from pytest_socket import SocketBlockedError

_TOKEN = "unit-test-token"  # noqa: S105 — a fixture value, not a secret

#: A synthetic value shaped like a contact identifier — never real PII, but shaped so a bug that
#: leaks row content into an error would be caught by the scan below.
_FIXTURE_CONTACT_VALUE = "patient137@example-fixture.test"


def _row(
    subject_key: str,
    *,
    event_time: str,
    channel: str = "email",
    to_state: str = "opted_in",
    message_id: str = "msg-0001",
) -> dict[str, object]:
    return {
        "subject_key": subject_key,
        "channel": channel,
        "to_state": to_state,
        "message_id": message_id,
        "event_time": event_time,
    }


class InMemoryCursorStore:
    """CursorStore fake for reader-level tests; the HTTP store has its own boundary test."""

    def __init__(self) -> None:
        self.cursor: dict[str, object] | None = None
        self.saves: list[dict[str, object]] = []

    def load(self) -> Mapping[str, object] | None:
        return self.cursor

    def save(self, cursor: Mapping[str, object]) -> None:
        canonical = validate_cursor(cursor)
        self.cursor = canonical
        self.saves.append(canonical)


class RecordingSource:
    """Wraps a RowSource and records every `after` argument, to prove no page is re-read."""

    def __init__(self, source: FixtureRowSource) -> None:
        self._source = source
        self.after_values: list[str | None] = []

    def fetch(self, *, after: str | None, limit: int) -> Sequence[Mapping[str, object]]:
        self.after_values.append(after)
        return self._source.fetch(after=after, limit=limit)


def test_sockets_are_blocked_for_this_module_too() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket()


class TestNoLiveNetwork:
    """Scenario: The test suite runs with no live network."""

    def test_a_fixture_backed_read_yields_validated_rows(self) -> None:
        rows = [
            _row("subj-a", event_time="2026-08-01T00:00:00+00:00"),
            _row("subj-b", event_time="2026-08-01T01:00:00+00:00"),
        ]
        reader = ConsentRowReader(FixtureRowSource(rows), InMemoryCursorStore())

        (page,) = list(reader.batches())

        assert page.errors == []
        assert [row.subject_key for row in page.rows] == ["subj-a", "subj-b"]
        for row in page.rows:
            assert isinstance(row, ConsentRow)
            assert isinstance(row.event_time, datetime)
            assert row.event_time.tzinfo is not None

    def test_every_contract_column_is_present_on_every_validated_row(self) -> None:
        rows = [_row("subj-a", event_time="2026-08-01T00:00:00+00:00")]
        reader = ConsentRowReader(FixtureRowSource(rows), InMemoryCursorStore())

        (page,) = list(reader.batches())

        (row,) = page.rows
        for column in CONTRACT_COLUMNS:
            assert hasattr(row, column)


class TestMalformedRowsAmongValidOnes:
    """Scenario: A malformed row among valid ones."""

    def test_malformed_rows_are_collected_while_valid_rows_still_yield(self) -> None:
        good_one = _row("subj-a", event_time="2026-08-01T00:00:00+00:00")
        bad = _row("subj-b", event_time="2026-08-01T01:00:00+00:00")
        del bad["to_state"]
        good_two = _row("subj-c", event_time="2026-08-01T02:00:00+00:00")
        reader = ConsentRowReader(FixtureRowSource([good_one, bad, good_two]), InMemoryCursorStore())

        (page,) = list(reader.batches())

        assert [row.subject_key for row in page.rows] == ["subj-a", "subj-c"]
        assert len(page.errors) == 1
        (error,) = page.errors
        assert isinstance(error, RowError)
        assert error.row_index == 1
        assert error.column == "to_state"

    def test_unparseable_event_time_is_collected_naming_the_column(self) -> None:
        bad = _row("subj-a", event_time="not-a-timestamp")
        reader = ConsentRowReader(FixtureRowSource([bad]), InMemoryCursorStore())

        (page,) = list(reader.batches())

        assert page.rows == []
        (error,) = page.errors
        assert error.column == "event_time"

    def test_naive_event_time_is_collected_naming_the_column(self) -> None:
        bad = _row("subj-a", event_time="2026-08-01T00:00:00")
        reader = ConsentRowReader(FixtureRowSource([bad]), InMemoryCursorStore())

        (page,) = list(reader.batches())

        assert page.rows == []
        (error,) = page.errors
        assert error.column == "event_time"

    def test_no_fixture_contact_value_appears_in_any_row_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """The PHI exit this module owns: a row error never carries the row's own field values,
        only the offending column's name and a generic detail — asserted against both the
        returned `RowError`s and anything the run happened to log."""
        contact_shaped = _row("subj-a", event_time="2026-08-01T00:00:00+00:00", message_id=_FIXTURE_CONTACT_VALUE)
        del contact_shaped["channel"]
        reader = ConsentRowReader(FixtureRowSource([contact_shaped]), InMemoryCursorStore())

        with caplog.at_level("DEBUG"):
            (page,) = list(reader.batches())

        (error,) = page.errors
        assert _FIXTURE_CONTACT_VALUE not in error.detail
        assert _FIXTURE_CONTACT_VALUE not in str(error)
        assert _FIXTURE_CONTACT_VALUE not in caplog.text


class TestCursorBoundary:
    """Scenario: a page split across a cursor boundary resumes without re-reading."""

    def test_resume_continues_from_the_persisted_cursor_without_rereading(self) -> None:
        rows = [
            _row("subj-a", event_time="2026-08-01T00:00:00+00:00"),
            _row("subj-b", event_time="2026-08-01T01:00:00+00:00"),
            _row("subj-c", event_time="2026-08-01T02:00:00+00:00"),
            _row("subj-d", event_time="2026-08-01T03:00:00+00:00"),
        ]
        store = InMemoryCursorStore()

        first_source = RecordingSource(FixtureRowSource(rows))
        first_reader = ConsentRowReader(first_source, store, page_size=2)
        first_batches = first_reader.batches()
        page_one = next(first_batches)
        assert [row.subject_key for row in page_one.rows] == ["subj-a", "subj-b"]
        first_reader.commit()
        del first_batches  # crash: run 1 never fetches page 2

        second_source = RecordingSource(FixtureRowSource(rows))
        second_reader = ConsentRowReader(second_source, store, page_size=2)
        remaining = list(second_reader.batches())

        assert second_source.after_values[0] == "2026-08-01T01:00:00+00:00"
        yielded = [row.subject_key for page in remaining for row in page.rows]
        assert yielded == ["subj-c", "subj-d"]

    def test_a_page_with_no_valid_rows_halts_instead_of_looping_forever(self) -> None:
        """`FixtureRowSource` always re-surfaces a row whose `event_time` never parsed, so a page
        with no valid row at all has no boundary to page past. The reader must yield it once and
        stop rather than re-fetch the identical page forever."""
        bad = _row("subj-a", event_time="not-a-timestamp")
        good = _row("subj-b", event_time="2026-08-01T00:00:00+00:00")
        store = InMemoryCursorStore()
        source = RecordingSource(FixtureRowSource([bad, good]))
        reader = ConsentRowReader(source, store, page_size=1)

        pages = list(reader.batches())

        assert len(pages) == 1
        assert pages[0].rows == []
        assert len(pages[0].errors) == 1

    def test_a_trailing_malformed_row_with_a_parseable_event_time_is_not_recounted_across_pages(self) -> None:
        """A malformed row's own timestamp can still parse even though another column doesn't; the
        cursor must advance past it too, or the next `fetch(after=...)` call re-surfaces the exact
        same row and it validates (and fails) a second time — double-counting one physical
        malformed row as two distinct `RowError`s. Regression for the crash-resume replay bug
        flagged in task 3.3's handoff."""
        good_one = _row("subj-a", event_time="2026-08-01T00:00:00+00:00")
        bad = _row("subj-b", event_time="2026-08-01T01:00:00+00:00")
        del bad["to_state"]
        good_two = _row("subj-c", event_time="2026-08-01T02:00:00+00:00")
        store = InMemoryCursorStore()
        source = RecordingSource(FixtureRowSource([good_one, bad, good_two]))
        reader = ConsentRowReader(source, store, page_size=2)

        pages = list(reader.batches())

        assert source.after_values == [
            None,
            "2026-08-01T01:00:00+00:00",
            "2026-08-01T02:00:00+00:00",
        ]
        all_errors = [error for page in pages for error in page.errors]
        assert len(all_errors) == 1
        assert all_errors[0].column == "to_state"
        yielded = [row.subject_key for page in pages for row in page.rows]
        assert yielded == ["subj-a", "subj-c"]

    def test_commit_persists_a_json_native_cursor(self) -> None:
        rows = [_row("subj-a", event_time="2026-08-01T00:00:00+00:00")]
        store = InMemoryCursorStore()
        reader = ConsentRowReader(FixtureRowSource(rows), store)
        list(reader.batches())
        reader.commit()

        assert len(store.saves) == 1
        cursor = store.saves[0]
        assert cursor == validate_cursor(cursor)
        assert cursor["event_time"] == "2026-08-01T00:00:00+00:00"


class TestFixtureRowSourcePaging:
    def test_a_page_never_splits_an_event_time_tie(self) -> None:
        tie = "2026-08-01T00:00:00+00:00"
        rows = [
            _row("subj-a", event_time=tie),
            _row("subj-b", event_time=tie),
            _row("subj-c", event_time="2026-08-01T01:00:00+00:00"),
        ]
        source = FixtureRowSource(rows)

        page = source.fetch(after=None, limit=1)

        assert [row["subject_key"] for row in page] == ["subj-a", "subj-b"]

    def test_fetch_after_excludes_earlier_and_equal_event_time(self) -> None:
        rows = [
            _row("subj-a", event_time="2026-08-01T00:00:00+00:00"),
            _row("subj-b", event_time="2026-08-01T01:00:00+00:00"),
        ]
        source = FixtureRowSource(rows)

        page = source.fetch(after="2026-08-01T00:00:00+00:00", limit=10)

        assert [row["subject_key"] for row in page] == ["subj-b"]


class TestLedgerCursorStore:
    """The HTTP store speaks the ledger's writer-state wire contract, faked at the httpx boundary."""

    def _fake_ledger(self) -> tuple[httpx.MockTransport, dict[str, Any]]:
        state: dict[str, Any] = {"cursor": None, "requests": []}

        def handler(request: httpx.Request) -> httpx.Response:
            state["requests"].append(request)
            if request.method == "GET":
                if state["cursor"] is None:
                    return httpx.Response(404, json={"detail": "no cursor persisted for writer 'consent-ingress'"})
                return httpx.Response(
                    200,
                    json={
                        "writer_id": "consent-ingress",
                        "cursor": state["cursor"],
                        "updated_at": "2026-08-01T00:00:00+00:00",
                    },
                )
            if request.method == "PUT":
                state["cursor"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "writer_id": "consent-ingress",
                        "cursor": state["cursor"],
                        "updated_at": "2026-08-01T00:00:00+00:00",
                    },
                )
            return httpx.Response(405)

        return httpx.MockTransport(handler), state

    def test_load_returns_none_before_any_cursor_is_persisted(self) -> None:
        transport, _ = self._fake_ledger()
        store = LedgerCursorStore("http://ledger", writer_id="consent-ingress", token=_TOKEN, transport=transport)

        assert store.load() is None

    def test_save_then_load_round_trips_through_the_writer_state_route(self) -> None:
        transport, state = self._fake_ledger()
        store = LedgerCursorStore("http://ledger", writer_id="consent-ingress", token=_TOKEN, transport=transport)
        cursor = {"event_time": "2026-08-01T00:00:00+00:00"}

        store.save(cursor)
        loaded = store.load()

        assert loaded == cursor
        put = next(r for r in state["requests"] if r.method == "PUT")
        assert put.url.path == cursor_path("consent-ingress")
        assert json.loads(put.content) == cursor
        assert put.headers["Authorization"] == f"Bearer {_TOKEN}"

    def test_save_rejects_a_cursor_that_is_not_json_native(self) -> None:
        transport, state = self._fake_ledger()
        store = LedgerCursorStore("http://ledger", writer_id="consent-ingress", token=_TOKEN, transport=transport)

        with pytest.raises(Exception, match="JSON-native"):
            store.save({"event_time": datetime(2026, 8, 1)})
        assert state["requests"] == []
