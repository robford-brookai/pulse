"""Gate 5: Glue Script Logic.

Unit tests for the scaffold's own code — scripts/dispatch_tasks.py and
scripts/collect_handoffs.py — on hand-built fixtures.

Usage: uv run pytest tests/scaffold/cat5_glue_logic.py -v
"""

from pathlib import Path

from ._scaffold import load_script

dispatch = load_script("dispatch_tasks.py")
collect = load_script("collect_handoffs.py")

TASKS_MD = """\
# Tasks

## Milestone 1: Parser

- [ ] Build the tasks parser
  Must handle milestone headers.
  And multi-line bodies.
- [x] Already finished task

## Milestone 2: Emitter

- [X] Uppercase done marker
- [ ] Emit work orders
"""


# --- dispatch_tasks.parse_tasks ----------------------------------------------------------------


def test_parse_tasks_titles_in_order(tmp_path: Path) -> None:
    md = tmp_path / "tasks.md"
    md.write_text(TASKS_MD)
    tasks = dispatch.parse_tasks(md)
    assert [t["title"] for t in tasks] == [
        "Build the tasks parser",
        "Already finished task",
        "Uppercase done marker",
        "Emit work orders",
    ]


def test_parse_tasks_attributes_milestones(tmp_path: Path) -> None:
    md = tmp_path / "tasks.md"
    md.write_text(TASKS_MD)
    tasks = dispatch.parse_tasks(md)
    assert [t["milestone"] for t in tasks] == [
        "Milestone 1: Parser",
        "Milestone 1: Parser",
        "Milestone 2: Emitter",
        "Milestone 2: Emitter",
    ]


def test_parse_tasks_captures_body_lines(tmp_path: Path) -> None:
    md = tmp_path / "tasks.md"
    md.write_text(TASKS_MD)
    tasks = dispatch.parse_tasks(md)
    assert tasks[0]["body"] == ["  Must handle milestone headers.", "  And multi-line bodies."]
    assert tasks[1]["body"] == []


def test_parse_tasks_reads_done_flag_case_insensitively(tmp_path: Path) -> None:
    md = tmp_path / "tasks.md"
    md.write_text(TASKS_MD)
    tasks = dispatch.parse_tasks(md)
    assert [t["done"] for t in tasks] == [False, True, True, False]


# --- dispatch_tasks.emit_work_orders -----------------------------------------------------------


def test_emit_work_orders_filenames_are_zero_padded(tmp_path: Path) -> None:
    tasks = [{"milestone": "M", "title": f"Task {i}", "body": [], "done": False} for i in range(3)]
    paths = dispatch.emit_work_orders(tasks, "add-auth", tmp_path / "out")
    assert [p.name for p in paths] == ["task-001.md", "task-002.md", "task-003.md"]


def test_emit_work_orders_embeds_change_and_sections(tmp_path: Path) -> None:
    tasks = [{"milestone": "M1", "title": "Build parser", "body": [], "done": False}]
    (path,) = dispatch.emit_work_orders(tasks, "add-auth", tmp_path / "out")
    text = path.read_text()
    for expected in (
        "# Work Order: Build parser",
        "**Change**: add-auth",
        "**Milestone**: M1",
        "**Task ID**: task-001",
        "## Objective",
        "## Requirements",
        "## Agent Instructions",
        "openspec/changes/add-auth/specs/",
    ):
        assert expected in text, f"work order missing {expected!r}"


def test_emit_work_orders_context_section_only_when_body_present(tmp_path: Path) -> None:
    with_body = [{"milestone": "M", "title": "A", "body": ["  detail"], "done": False}]
    without_body = [{"milestone": "M", "title": "B", "body": [], "done": False}]
    (a,) = dispatch.emit_work_orders(with_body, "c", tmp_path / "a")
    (b,) = dispatch.emit_work_orders(without_body, "c", tmp_path / "b")
    assert "## Context" in a.read_text()
    assert "## Context" not in b.read_text()


def test_emit_work_orders_creates_missing_output_dir(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "out"
    tasks = [{"milestone": "M", "title": "A", "body": [], "done": False}]
    dispatch.emit_work_orders(tasks, "c", target)
    assert target.is_dir()


# --- collect_handoffs --------------------------------------------------------------------------


def _worktree(base: Path, name: str, handoff: str | None) -> Path:
    wt = base / name
    wt.mkdir(parents=True)
    if handoff is not None:
        (wt / "HANDOFF.md").write_text(handoff)
    return wt


def test_collect_handoffs_copies_only_worktrees_that_have_one(tmp_path: Path) -> None:
    has = _worktree(tmp_path / "wt", "task-001", "# HANDOFF\n")
    missing = _worktree(tmp_path / "wt", "task-002", None)
    out = collect.collect_handoffs([has, missing], "add-auth", tmp_path / "out")
    assert [p.name for p in out] == ["task-001.md"]


def test_collect_handoffs_names_files_after_the_worktree(tmp_path: Path) -> None:
    wt = _worktree(tmp_path / "wt", "feature-branch", "# HANDOFF\ncontent\n")
    (dest,) = collect.collect_handoffs([wt], "c", tmp_path / "out")
    assert dest.name == "feature-branch.md"
    assert dest.read_text() == "# HANDOFF\ncontent\n"


def test_summarize_handoffs_references_every_file(tmp_path: Path) -> None:
    paths = []
    for name in ("a", "b", "c"):
        p = tmp_path / f"{name}.md"
        p.write_text("x")
        paths.append(p)
    summary = collect.summarize_handoffs(paths, "add-auth")
    assert "Collected 3 handoff(s)." in summary
    for p in paths:
        assert p.name in summary
    assert "openspec/changes/add-auth/specs/" in summary


def test_summarize_handoffs_documents_the_empty_case() -> None:
    assert collect.summarize_handoffs([], "add-auth") == ("No HANDOFF.md files found for change 'add-auth'.")
