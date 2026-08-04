"""`pulse_core.cursor` — the JSON-native validation both the writer and the ledger rely on."""

from __future__ import annotations

import math

import pytest
from pulse_core.cursor import CURSOR_PATH_TEMPLATE, InvalidCursorError, cursor_path, validate_cursor


def test_cursor_path_fills_in_the_writer_id() -> None:
    assert cursor_path("verdict-relay") == "/writers/verdict-relay/cursor"


def test_the_path_template_is_a_fastapi_style_placeholder() -> None:
    assert CURSOR_PATH_TEMPLATE == "/writers/{writer_id}/cursor"


class TestValidateCursor:
    def test_a_plain_mapping_round_trips(self) -> None:
        cursor = {"batch": 7, "computed_at": "2026-08-03T00:00:00+00:00", "done": True, "note": None}
        assert validate_cursor(cursor) == cursor

    def test_nested_mappings_and_sequences_round_trip(self) -> None:
        cursor = {"offsets": {"a": [1, 2, 3], "b": []}}
        assert validate_cursor(cursor) == cursor

    def test_a_finite_float_round_trips(self) -> None:
        assert validate_cursor({"watermark": 3.5}) == {"watermark": 3.5}

    def test_a_non_mapping_top_level_is_rejected(self) -> None:
        with pytest.raises(InvalidCursorError) as excinfo:
            validate_cursor([1, 2, 3])  # type: ignore[arg-type]
        assert excinfo.value.path == "cursor"

    def test_a_non_string_key_is_rejected(self) -> None:
        with pytest.raises(InvalidCursorError):
            validate_cursor({1: "x"})  # type: ignore[dict-item]

    def test_a_non_finite_float_is_rejected(self) -> None:
        with pytest.raises(InvalidCursorError) as excinfo:
            validate_cursor({"watermark": math.inf})
        assert excinfo.value.path == "cursor.watermark"

    def test_a_value_with_no_json_spelling_is_rejected_and_named_by_path(self) -> None:
        with pytest.raises(InvalidCursorError) as excinfo:
            validate_cursor({"offsets": {"nested": object()}})
        assert excinfo.value.path == "cursor.offsets.nested"

    def test_a_datetime_is_rejected(self) -> None:
        from datetime import datetime, timezone

        with pytest.raises(InvalidCursorError):
            validate_cursor({"as_of": datetime(2026, 8, 3, tzinfo=timezone.utc)})
