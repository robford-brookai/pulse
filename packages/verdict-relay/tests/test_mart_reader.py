"""`verdict_relay.mart_reader` — contract validation, (subject, as_of) ordering, durable cursor.

Covers the verdict-mart-read scenarios: "A batch yields subject-grouped, as_of-ordered rows" and
"Crash and resume without re-reading". All rows are synthetic; the cursor endpoint is faked at the
httpx boundary (`httpx.MockTransport`), never mocked driver internals.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from pulse_core.cursor import cursor_path, validate_cursor
from verdict_relay.mart_reader import (
    CONTRACT_COLUMNS,
    FixtureRowSource,
    LedgerCursorStore,
    MartContractError,
    MartReader,
    MartRow,
)

_TOKEN = "unit-test-token"  # noqa: S105 — a fixture value, not a secret


def _row(
    subject_id: str,
    *,
    as_of: str,
    computed_at: str,
    verdict_type: str = "eligibility",
    outcome: str = "eligible",
    reason: str | None = None,
    rule_version: str = "rules-v1",
    lineage_ref: str = "dbt-run-0001",
) -> dict[str, object]:
    return {
        "subject_id": subject_id,
        "verdict_type": verdict_type,
        "outcome": outcome,
        "reason": reason,
        "rule_version": rule_version,
        "as_of": as_of,
        "lineage_ref": lineage_ref,
        "computed_at": computed_at,
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


class TestOrderedBatchShape:
    """Scenario: A batch yields subject-grouped, as_of-ordered rows."""

    def test_batch_is_subject_grouped_and_as_of_ordered(self) -> None:
        rows = [
            _row("subj-b", as_of="2026-08-02T00:00:00+00:00", computed_at="2026-08-03T01:00:00+00:00"),
            _row("subj-a", as_of="2026-08-03T00:00:00+00:00", computed_at="2026-08-03T02:00:00+00:00"),
            _row("subj-b", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T03:00:00+00:00"),
            _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T04:00:00+00:00"),
        ]
        reader = MartReader(RecordingSource(FixtureRowSource(rows)), InMemoryCursorStore())

        batches = list(reader.batches())

        assert len(batches) == 1
        batch = batches[0]
        assert [(r.subject_id, r.as_of.isoformat()) for r in batch] == [
            ("subj-a", "2026-08-01T00:00:00+00:00"),
            ("subj-a", "2026-08-03T00:00:00+00:00"),
            ("subj-b", "2026-08-01T00:00:00+00:00"),
            ("subj-b", "2026-08-02T00:00:00+00:00"),
        ]

    def test_every_contract_column_is_present_on_every_row(self) -> None:
        rows = [_row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T00:00:00+00:00")]
        reader = MartReader(FixtureRowSource(rows), InMemoryCursorStore())

        (batch,) = reader.batches()

        (mart_row,) = batch
        assert isinstance(mart_row, MartRow)
        for column in CONTRACT_COLUMNS:
            assert hasattr(mart_row, column)
        assert isinstance(mart_row.as_of, datetime)
        assert isinstance(mart_row.computed_at, datetime)
        assert mart_row.as_of.tzinfo is not None
        assert mart_row.computed_at.tzinfo is not None


class TestContractValidation:
    """A row that violates the contract fails the run before any row of its page is yielded."""

    def test_missing_column_fails_naming_the_row(self) -> None:
        good = _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T00:00:00+00:00")
        bad = _row("subj-b", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T01:00:00+00:00")
        del bad["rule_version"]
        reader = MartReader(FixtureRowSource([good, bad]), InMemoryCursorStore())

        with pytest.raises(MartContractError, match=r"rule_version") as excinfo:
            list(reader.batches())
        assert "subj-b" in str(excinfo.value)

    def test_unparseable_timestamp_fails_naming_the_row(self) -> None:
        bad = _row("subj-a", as_of="not-a-timestamp", computed_at="2026-08-03T00:00:00+00:00")
        reader = MartReader(FixtureRowSource([bad]), InMemoryCursorStore())

        with pytest.raises(MartContractError, match=r"as_of") as excinfo:
            list(reader.batches())
        assert "subj-a" in str(excinfo.value)

    def test_naive_timestamp_fails_naming_the_row(self) -> None:
        bad = _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T00:00:00")
        reader = MartReader(FixtureRowSource([bad]), InMemoryCursorStore())

        with pytest.raises(MartContractError, match=r"computed_at") as excinfo:
            list(reader.batches())
        assert "subj-a" in str(excinfo.value)

    def test_a_violating_page_yields_no_rows(self) -> None:
        bad = _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T00:00:00+00:00")
        del bad["lineage_ref"]
        reader = MartReader(FixtureRowSource([bad]), InMemoryCursorStore())
        batches = reader.batches()

        with pytest.raises(MartContractError):
            next(batches)


class TestCrashAndResume:
    """Scenario: Crash and resume without re-reading."""

    def test_resume_continues_from_the_persisted_cursor_without_rereading(self) -> None:
        rows = [
            _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T01:00:00+00:00"),
            _row("subj-b", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T02:00:00+00:00"),
            _row("subj-a", as_of="2026-08-02T00:00:00+00:00", computed_at="2026-08-03T03:00:00+00:00"),
            _row("subj-b", as_of="2026-08-02T00:00:00+00:00", computed_at="2026-08-03T04:00:00+00:00"),
        ]
        store = InMemoryCursorStore()

        # Run 1: reads page 1, declares it, persists the cursor, then "crashes".
        first_source = RecordingSource(FixtureRowSource(rows))
        first_reader = MartReader(first_source, store, page_size=2)
        first_batches = first_reader.batches()
        page_one = next(first_batches)
        assert [r.computed_at.isoformat() for r in sorted(page_one, key=lambda r: r.computed_at)] == [
            "2026-08-03T01:00:00+00:00",
            "2026-08-03T02:00:00+00:00",
        ]
        for row in page_one:
            first_reader.record_declared(row.subject_id, row.as_of)
        first_reader.commit()
        del first_batches  # crash: run 1 never fetches page 2

        # Run 2: resumes from the persisted cursor.
        second_source = RecordingSource(FixtureRowSource(rows))
        second_reader = MartReader(second_source, store, page_size=2)
        remaining = list(second_reader.batches())

        assert second_source.after_values[0] == "2026-08-03T02:00:00+00:00"
        yielded = [r.computed_at.isoformat() for batch in remaining for r in batch]
        assert yielded == ["2026-08-03T03:00:00+00:00", "2026-08-03T04:00:00+00:00"]

    def test_resume_restores_the_per_subject_watermarks(self) -> None:
        rows = [_row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T01:00:00+00:00")]
        store = InMemoryCursorStore()
        first_reader = MartReader(FixtureRowSource(rows), store)
        (batch,) = first_reader.batches()
        first_reader.record_declared("subj-a", batch[0].as_of)
        first_reader.commit()

        second_reader = MartReader(FixtureRowSource(rows), store)
        list(second_reader.batches())

        watermark = second_reader.watermark("subj-a")
        assert watermark is not None
        assert watermark.isoformat() == "2026-08-01T00:00:00+00:00"
        assert second_reader.watermark("subj-never-declared") is None

    def test_record_declared_never_regresses_a_watermark(self) -> None:
        reader = MartReader(FixtureRowSource([]), InMemoryCursorStore())
        newer = datetime(2026, 8, 2, tzinfo=timezone.utc)
        older = datetime(2026, 8, 1, tzinfo=timezone.utc)

        reader.record_declared("subj-a", newer)
        reader.record_declared("subj-a", older)

        assert reader.watermark("subj-a") == newer

    def test_commit_persists_a_json_native_cursor_in_one_save(self) -> None:
        rows = [_row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T01:00:00+00:00")]
        store = InMemoryCursorStore()
        reader = MartReader(FixtureRowSource(rows), store)
        (batch,) = reader.batches()
        reader.record_declared("subj-a", batch[0].as_of)
        reader.commit()

        assert len(store.saves) == 1
        cursor = store.saves[0]
        assert cursor == validate_cursor(cursor)  # JSON-native round-trip
        assert cursor["computed_at"] == "2026-08-03T01:00:00+00:00"
        assert cursor["watermarks"] == {"subj-a": "2026-08-01T00:00:00+00:00"}


class TestFixtureRowSourcePaging:
    def test_a_page_never_splits_a_computed_at_tie(self) -> None:
        tie = "2026-08-03T01:00:00+00:00"
        rows = [
            _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at=tie),
            _row("subj-b", as_of="2026-08-01T00:00:00+00:00", computed_at=tie),
            _row("subj-c", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T02:00:00+00:00"),
        ]
        source = FixtureRowSource(rows)

        page = source.fetch(after=None, limit=1)

        assert [row["subject_id"] for row in page] == ["subj-a", "subj-b"]

    def test_fetch_after_excludes_earlier_and_equal_computed_at(self) -> None:
        rows = [
            _row("subj-a", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T01:00:00+00:00"),
            _row("subj-b", as_of="2026-08-01T00:00:00+00:00", computed_at="2026-08-03T02:00:00+00:00"),
        ]
        source = FixtureRowSource(rows)

        page = source.fetch(after="2026-08-03T01:00:00+00:00", limit=10)

        assert [row["subject_id"] for row in page] == ["subj-b"]


class TestLedgerCursorStore:
    """The HTTP store speaks the ledger's writer-state wire contract, faked at the httpx boundary."""

    def _fake_ledger(self) -> tuple[httpx.MockTransport, dict[str, Any]]:
        state: dict[str, Any] = {"cursor": None, "requests": []}

        def handler(request: httpx.Request) -> httpx.Response:
            state["requests"].append(request)
            if request.method == "GET":
                if state["cursor"] is None:
                    return httpx.Response(404, json={"detail": "no cursor persisted for writer 'verdict-relay'"})
                return httpx.Response(
                    200,
                    json={
                        "writer_id": "verdict-relay",
                        "cursor": state["cursor"],
                        "updated_at": "2026-08-03T00:00:00+00:00",
                    },
                )
            if request.method == "PUT":
                state["cursor"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "writer_id": "verdict-relay",
                        "cursor": state["cursor"],
                        "updated_at": "2026-08-03T00:00:00+00:00",
                    },
                )
            return httpx.Response(405)

        return httpx.MockTransport(handler), state

    def test_load_returns_none_before_any_cursor_is_persisted(self) -> None:
        transport, _ = self._fake_ledger()
        store = LedgerCursorStore("http://ledger", writer_id="verdict-relay", token=_TOKEN, transport=transport)

        assert store.load() is None

    def test_save_then_load_round_trips_through_the_writer_state_route(self) -> None:
        transport, state = self._fake_ledger()
        store = LedgerCursorStore("http://ledger", writer_id="verdict-relay", token=_TOKEN, transport=transport)
        cursor = {"computed_at": "2026-08-03T01:00:00+00:00", "watermarks": {"subj-a": "2026-08-01T00:00:00+00:00"}}

        store.save(cursor)
        loaded = store.load()

        assert loaded == cursor
        put = next(r for r in state["requests"] if r.method == "PUT")
        assert put.url.path == cursor_path("verdict-relay")
        assert json.loads(put.content) == cursor
        assert put.headers["Authorization"] == f"Bearer {_TOKEN}"

    def test_save_rejects_a_cursor_that_is_not_json_native(self) -> None:
        transport, state = self._fake_ledger()
        store = LedgerCursorStore("http://ledger", writer_id="verdict-relay", token=_TOKEN, transport=transport)

        with pytest.raises(Exception, match="JSON-native"):
            store.save({"as_of": datetime(2026, 8, 1, tzinfo=timezone.utc)})
        assert state["requests"] == []
