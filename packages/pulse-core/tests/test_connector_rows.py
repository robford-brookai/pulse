"""`pulse_core.connector.rows` — the inbound read contract, extracted from the shipped readers.

Covers the connector-kit spec's two read-contract scenarios: "A malformed row is named, the run
survives" and "A crashed run resumes from the durable cursor". All rows are synthetic; the cursor
endpoint is faked at the httpx boundary (`httpx.MockTransport`), never mocked driver internals.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx
import pytest
from pulse_core.connector import (
    FixtureRowSource,
    LedgerCursorStore,
    RowError,
    RowValidationError,
    required_string,
    required_timestamp,
    validate_page,
)
from pulse_core.cursor import cursor_path

_TOKEN = "unit-test-token"  # noqa: S105 — a fixture value, not a secret

#: A synthetic value shaped like a contact identifier — never real PII, but shaped so a bug that
#: leaks row content into an error would be caught by the scans below.
_FIXTURE_CONTACT_VALUE = "patient137@example-fixture.test"

_WRITER_ID = "kit-test-connector"


def _row(key: str, *, seen_at: str) -> dict[str, object]:
    return {"key": key, "contact": _FIXTURE_CONTACT_VALUE, "seen_at": seen_at}


def _validator(row: Mapping[str, object]) -> tuple[str, datetime]:
    """A minimal row validator built the way a connector builds one: from the kit helpers."""
    return (required_string(row, "key"), required_timestamp(row, "seen_at"))


class TestMalformedRowIsNamedRunSurvives:
    """Spec scenario: a page containing one row missing a contract column."""

    def test_error_names_position_and_column_and_the_rest_of_the_page_validates(self) -> None:
        page = [
            _row("a", seen_at="2026-08-01T00:00:00+00:00"),
            {"contact": _FIXTURE_CONTACT_VALUE, "seen_at": "2026-08-01T00:01:00+00:00"},  # no "key"
            _row("c", seen_at="2026-08-01T00:02:00+00:00"),
        ]

        validated = validate_page(page, _validator)

        assert [key for key, _ in validated.rows] == ["a", "c"]
        (error,) = validated.errors
        assert error == RowError(row_index=1, column="key", detail=error.detail)
        assert "key" in error.detail

    @pytest.mark.parametrize(
        "seen_at",
        [
            None,  # not a string
            f"contact:{_FIXTURE_CONTACT_VALUE}",  # not ISO-8601, value shaped like a contact
            "2026-08-01T00:00:00",  # timezone-naive
        ],
    )
    def test_no_payload_value_appears_in_a_timestamp_error(self, seen_at: object) -> None:
        row: dict[str, object] = {"key": "a", "contact": _FIXTURE_CONTACT_VALUE, "seen_at": seen_at}

        validated = validate_page([row], _validator)

        (error,) = validated.errors
        assert error.column == "seen_at"
        for leak in (_FIXTURE_CONTACT_VALUE, "2026-08-01T00:00:00"):
            assert leak not in error.detail
            assert leak not in str(error)

    def test_no_payload_value_appears_in_a_missing_string_error(self) -> None:
        validated = validate_page([{"key": "", "contact": _FIXTURE_CONTACT_VALUE}], _validator)

        (error,) = validated.errors
        assert error.column == "key"
        assert _FIXTURE_CONTACT_VALUE not in error.detail

    def test_helpers_raise_row_validation_error_carrying_the_column(self) -> None:
        with pytest.raises(RowValidationError) as excinfo:
            required_string({}, "key")
        assert excinfo.value.column == "key"

        with pytest.raises(RowValidationError) as excinfo:
            required_timestamp({"seen_at": "not-a-timestamp"}, "seen_at")
        assert excinfo.value.column == "seen_at"


class _CursorBackend:
    """One writer's cursor endpoint, faked at the httpx boundary over a plain dict."""

    def __init__(self) -> None:
        self.stored: dict[str, Any] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == cursor_path(_WRITER_ID)
        if request.method == "GET":
            if self.stored is None:
                return httpx.Response(404, json={"detail": "no cursor persisted"})
            return httpx.Response(200, json={"cursor": self.stored})
        assert request.method == "PUT"
        self.stored = json.loads(request.content)
        return httpx.Response(204)


def _store(backend: _CursorBackend) -> LedgerCursorStore:
    return LedgerCursorStore(
        "https://ledger.test",
        writer_id=_WRITER_ID,
        token=_TOKEN,
        transport=httpx.MockTransport(backend.handler),
    )


class TestCrashedRunResumesFromDurableCursor:
    """Spec scenario: a run persisted its cursor and then died mid-batch."""

    ROWS: ClassVar[list[dict[str, object]]] = [
        _row("a", seen_at="2026-08-01T00:00:00+00:00"),
        _row("b", seen_at="2026-08-01T00:01:00+00:00"),
        _row("c", seen_at="2026-08-01T00:02:00+00:00"),
    ]

    def test_a_fresh_store_resumes_from_the_persisted_position(self) -> None:
        backend = _CursorBackend()
        with _store(backend) as first_run:
            first_run.save({"seen_at": "2026-08-01T00:01:00+00:00"})
        # The first run dies here, mid-batch; the next run starts from a fresh store.
        with _store(backend) as next_run:
            cursor = next_run.load()

        assert cursor == {"seen_at": "2026-08-01T00:01:00+00:00"}
        after = cursor["seen_at"]
        assert isinstance(after, str)
        resumed = FixtureRowSource(self.ROWS, cursor_column="seen_at").fetch(after=after, limit=10)
        assert [row["key"] for row in resumed] == ["c"]

    def test_a_stale_cursor_re_reads_the_overlap_never_skips(self) -> None:
        """A crash before `save` resumes from the older position: the overlap rows re-surface
        (D16 classifies them as replays downstream) — the contract loses nothing either way."""
        backend = _CursorBackend()
        with _store(backend) as first_run:
            first_run.save({"seen_at": "2026-08-01T00:00:00+00:00"})
        with _store(backend) as next_run:
            cursor = next_run.load()

        assert cursor is not None
        after = cursor["seen_at"]
        assert isinstance(after, str)
        resumed = FixtureRowSource(self.ROWS, cursor_column="seen_at").fetch(after=after, limit=10)
        assert [row["key"] for row in resumed] == ["b", "c"]

    def test_a_writer_that_never_checkpointed_loads_none_and_reads_everything(self) -> None:
        backend = _CursorBackend()
        with _store(backend) as first_run:
            assert first_run.load() is None

        page = FixtureRowSource(self.ROWS, cursor_column="seen_at").fetch(after=None, limit=10)
        assert [row["key"] for row in page] == ["a", "b", "c"]


class TestFixtureRowSourcePaging:
    """The fetch contract the kit pins for every fixture-driven reader test."""

    def test_a_page_never_splits_a_cursor_column_tie(self) -> None:
        rows = [
            _row("a", seen_at="2026-08-01T00:00:00+00:00"),
            _row("b", seen_at="2026-08-01T00:01:00+00:00"),
            _row("c", seen_at="2026-08-01T00:01:00+00:00"),
        ]
        page = FixtureRowSource(rows, cursor_column="seen_at").fetch(after=None, limit=2)
        assert [row["key"] for row in page] == ["a", "b", "c"]

    def test_an_unparseable_cursor_value_always_resurfaces(self) -> None:
        rows = [{"key": "bad", "seen_at": "not-a-timestamp"}]
        source = FixtureRowSource(rows, cursor_column="seen_at")
        assert [row["key"] for row in source.fetch(after=None, limit=10)] == ["bad"]
        assert [row["key"] for row in source.fetch(after="2026-08-01T00:00:00+00:00", limit=10)] == ["bad"]


def test_required_timestamp_returns_the_parsed_instant() -> None:
    parsed = required_timestamp({"seen_at": "2026-08-01T00:00:00+00:00"}, "seen_at")
    assert parsed == datetime(2026, 8, 1, tzinfo=timezone.utc)
