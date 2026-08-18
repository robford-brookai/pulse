"""Smoke test for Demo 3's live kanban drag (task 7.1).

Demo 3 is the one demo that needs a live Twenty instance and a served ledger API, so — unlike
`test_demo2_kanban_drag.py` — this suite never runs the demo itself. Its contract is exactly what
the work order asks CI to hold with no server and no credentials: the script parses, exposes
`build_arg_parser()`, `--help` exits cleanly, importing it runs nothing and reads no environment,
and running it unconfigured is a fast named refusal rather than a hang or a traceback.

The one live-shaped thing CI does exercise is the view match (task 6.5): 7.2's first live contact
showed no `getCoreViews` and no `universalIdentifier` on `View`, so the board is now identified by
(object metadata id, KANBAN, name). That match runs here against a faked `getViews` payload in the
live shape, with synthetic values — no server, no credentials.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo3_live_kanban_drag.py"

spec = importlib.util.spec_from_file_location("demo3_live_kanban_drag", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo3 = importlib.util.module_from_spec(spec)
sys.modules["demo3_live_kanban_drag"] = demo3
spec.loader.exec_module(demo3)


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_an_argument_parser() -> None:
    import argparse

    assert isinstance(demo3.build_arg_parser(), argparse.ArgumentParser)


def test_default_args_parse_with_no_arguments() -> None:
    args = demo3.build_arg_parser().parse_args([])
    assert args.target == "dev"
    assert args.card_index == 0


def test_target_and_card_index_parse() -> None:
    args = demo3.build_arg_parser().parse_args(["--target", "dev", "--card-index", "3"])
    assert args.target == "dev"
    assert args.card_index == 3


def test_an_unknown_target_is_refused_at_parse_time() -> None:
    with pytest.raises(SystemExit):
        demo3.build_arg_parser().parse_args(["--target", "nowhere"])


def test_main_with_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        demo3.main(["--help"])
    assert raised.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_check_raises_demo_assertion_error_on_a_false_condition() -> None:
    with pytest.raises(demo3.DemoAssertionError, match="boom"):
        demo3._check(False, "boom")


def test_check_is_a_no_op_on_a_true_condition() -> None:
    demo3._check(True, "unreachable")


def test_main_unconfigured_refuses_fast_naming_the_missing_variables(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No credentials means a named refusal before any socket is opened — CI-safe by construction."""
    exit_code = demo3.main([], env={})
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "PULSE_TWENTY_DEV_URL" in captured.err
    assert "PULSE_TWENTY_DEV_TOKEN" in captured.err


def test_main_unconfigured_names_the_ledger_variables_too(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = demo3.main(
        [],
        env={"PULSE_TWENTY_DEV_URL": "https://twenty.example", "PULSE_TWENTY_DEV_TOKEN": "token"},
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "PULSE_LEDGER_API_URL" in captured.err
    assert "PULSE_LEDGER_TWENTY_WEBHOOK_SECRET" in captured.err


def test_the_script_run_as_a_subprocess_with_help_exits_zero_with_no_network() -> None:
    """The runnable-script contract: `python demo3_live_kanban_drag.py --help` exits cleanly."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "Demo 3" in result.stdout


def test_main_is_not_invoked_by_importing_the_module() -> None:
    """Guarded by `if __name__ == "__main__"` — importing it for testing must not run the demo."""
    assert demo3.__name__ != "__main__"


# --- The view match (task 6.5) ---------------------------------------------------------------------

#: Synthetic metadata ids. Shaped like Twenty's uuids, tied to nothing live.
BOARD_OBJECT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_OBJECT_ID = "22222222-2222-4222-8222-222222222222"
STATUS_FIELD_ID = "33333333-3333-4333-8333-333333333333"


def _view(**overrides: Any) -> dict[str, Any]:
    """One record in the live `getViews` shape — note: no `universalIdentifier` field exists."""
    record = {
        "id": "44444444-4444-4444-8444-444444444444",
        "name": demo3.VIEW_NAME,
        "type": "KANBAN",
        "objectMetadataId": BOARD_OBJECT_ID,
        "mainGroupByFieldMetadataId": STATUS_FIELD_ID,
        "viewGroups": [{"fieldValue": "PENDING_START", "isVisible": True}],
    }
    return record | overrides


class _FakeViewReader:
    """Answers exactly one GraphQL read with a canned `getViews` payload."""

    def __init__(self, views: list[dict[str, Any]]) -> None:
        self._views = views
        self.calls: list[tuple[str, str]] = []

    def graphql(self, path: str, query: str) -> dict[str, Any]:
        self.calls.append((path, query))
        return {"getViews": self._views}


def test_the_views_query_reads_getviews_on_the_metadata_graphql() -> None:
    """The pin 7.2 falsified: not `getCoreViews`, and not `/graphql`."""
    assert "getViews" in demo3.VIEWS_QUERY
    assert "getCoreViews" not in demo3.VIEWS_QUERY
    assert "universalIdentifier" not in demo3.VIEWS_QUERY
    assert demo3.GRAPHQL_PATH == "/metadata"


def test_the_pinned_view_name_is_the_name_the_app_publishes() -> None:
    """The match keys on the name, so a rename in the app source must not silently miss."""
    source = (REPO_ROOT / "packages/twenty-app/src/views/patient-program-lifecycle-board.view.ts").read_text()
    assert f'name: "{demo3.VIEW_NAME}"' in source


def test_match_found_when_object_type_and_name_all_agree() -> None:
    matches = demo3.match_board_views([_view()], BOARD_OBJECT_ID)
    assert len(matches) == 1
    assert matches[0]["id"] == _view()["id"]


def test_no_match_when_the_view_belongs_to_another_object() -> None:
    assert demo3.match_board_views([_view(objectMetadataId=OTHER_OBJECT_ID)], BOARD_OBJECT_ID) == []


def test_no_match_when_the_view_is_the_table_view_of_the_same_object() -> None:
    """Object id alone would take this one — the type is part of the identity now."""
    assert demo3.match_board_views([_view(type="TABLE")], BOARD_OBJECT_ID) == []


def test_no_match_when_another_kanban_on_the_object_carries_a_different_name() -> None:
    assert demo3.match_board_views([_view(name="Status Board")], BOARD_OBJECT_ID) == []


def test_two_matches_are_both_returned_so_the_step_can_refuse() -> None:
    duplicate = _view(id="55555555-5555-4555-8555-555555555555")
    assert len(demo3.match_board_views([_view(), duplicate], BOARD_OBJECT_ID)) == 2


def test_step_view_shape_returns_the_matched_view_on_a_clean_payload() -> None:
    reader = _FakeViewReader([_view(), _view(objectMetadataId=OTHER_OBJECT_ID)])
    view = demo3.step_view_shape(reader, BOARD_OBJECT_ID, STATUS_FIELD_ID)
    assert view["mainGroupByFieldMetadataId"] == STATUS_FIELD_ID
    assert reader.calls == [(demo3.GRAPHQL_PATH, demo3.VIEWS_QUERY)]


def test_step_view_shape_fails_when_no_view_matches() -> None:
    reader = _FakeViewReader([_view(type="TABLE")])
    with pytest.raises(demo3.DemoAssertionError, match="found 0"):
        demo3.step_view_shape(reader, BOARD_OBJECT_ID, STATUS_FIELD_ID)


def test_step_view_shape_fails_when_two_views_match() -> None:
    reader = _FakeViewReader([_view(), _view(id="55555555-5555-4555-8555-555555555555")])
    with pytest.raises(demo3.DemoAssertionError, match="found 2"):
        demo3.step_view_shape(reader, BOARD_OBJECT_ID, STATUS_FIELD_ID)


def test_step_view_shape_fails_when_the_board_groups_on_another_field() -> None:
    reader = _FakeViewReader([_view(mainGroupByFieldMetadataId=OTHER_OBJECT_ID)])
    with pytest.raises(demo3.DemoAssertionError, match="groups on field id"):
        demo3.step_view_shape(reader, BOARD_OBJECT_ID, STATUS_FIELD_ID)


def test_column_parity_reads_the_matched_views_groups() -> None:
    """Assertion 3 is unchanged by the re-key: it still reads `viewGroups` off the matched view."""
    with pytest.raises(demo3.DemoAssertionError, match="column parity failed"):
        demo3.step_column_parity(_view())


# --- The rejection-note count (task 6.7) ------------------------------------------------------------

#: Synthetic record ids in Twenty's uuid shape, tied to nothing live.
CARD_RECORD_ID = "66666666-6666-4666-8666-666666666666"
OTHER_RECORD_ID = "77777777-7777-4777-8777-777777777777"


class _FakeNoteTargetReader:
    """Answers `_get` with canned `noteTargets` pages — the surface `count_comments` reads."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((path, params))
        return self._pages[len(self.calls) - 1]


def _note_target_page(records: list[dict[str, Any]], *, cursor: str | None = None) -> dict[str, Any]:
    page: dict[str, Any] = {"data": {demo3.NOTE_TARGETS_PLURAL: records}}
    if cursor is not None:
        page["pageInfo"] = {"hasNextPage": True, "endCursor": cursor}
    return page


def test_the_note_target_pin_reads_the_flat_relation_column() -> None:
    """The pin 7.2 falsified: no `comment` object — bindings carry `patientProgramId`, flat."""
    assert demo3.NOTE_TARGETS_PLURAL == "noteTargets"
    assert demo3.NOTE_TARGET_RECORD_COLUMN == "patientProgramId"


def test_count_comments_counts_only_bindings_on_the_given_record() -> None:
    reader = _FakeNoteTargetReader([
        _note_target_page([
            {"id": "nt-1", "noteId": "note-1", "patientProgramId": CARD_RECORD_ID},
            {"id": "nt-2", "noteId": "note-2", "patientProgramId": OTHER_RECORD_ID},
            {"id": "nt-3", "noteId": "note-3", "patientProgramId": CARD_RECORD_ID},
        ])
    ])

    count = demo3.TwentyReader.count_comments(reader, CARD_RECORD_ID)

    assert count == 2
    assert reader.calls[0][0] == "/rest/noteTargets"


def test_count_comments_walks_every_page() -> None:
    reader = _FakeNoteTargetReader([
        _note_target_page([{"id": "nt-1", "noteId": "note-1", "patientProgramId": CARD_RECORD_ID}], cursor="c1"),
        _note_target_page([{"id": "nt-2", "noteId": "note-2", "patientProgramId": CARD_RECORD_ID}]),
    ])

    count = demo3.TwentyReader.count_comments(reader, CARD_RECORD_ID)

    assert count == 2
    assert len(reader.calls) == 2
    assert reader.calls[1][1] == {"limit": 60, "starting_after": "c1"}


def test_count_comments_is_zero_when_no_binding_matches() -> None:
    reader = _FakeNoteTargetReader([
        _note_target_page([{"id": "nt-1", "noteId": "note-1", "patientProgramId": OTHER_RECORD_ID}])
    ])

    assert demo3.TwentyReader.count_comments(reader, CARD_RECORD_ID) == 0
