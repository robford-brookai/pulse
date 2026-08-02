"""Gate 5: Glue Script Logic.

Unit tests for the scaffold's own code — scripts/dispatch_tasks.py and
scripts/collect_handoffs.py — on hand-built fixtures.

Usage: uv run pytest tests/scaffold/cat5_glue_logic.py -v
"""

from pathlib import Path

import pytest

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


# --- dispatch_tasks: lane, wave and serial gates -----------------------------------------------
#
# These encode a real failure: dispatch emitted an Orca work order for an MSK teardown and a
# repo archive, because it parsed checkboxes and nothing else. WORKFLOW.md v2 excludes
# destructive_ops from the dispatch step; the script did not know lanes existed.

ANNOTATED_MD = """\
# Tasks

## 1. Group

- [x] 1.1 Already merged  `[lane: repo_change | wave: 0]`
- [ ] 1.2 Serial root edit  `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      `serial: workspace_roots` — edits the workspace manifest.
- [ ] 1.3 Parallel A  `[deps: 1.1 | lane: repo_change | wave: 1]`
- [ ] 1.4 Teardown  `[deps: 1.3 | lane: destructive_ops | wave: post-merge]`
"""


def _parse(tmp_path: Path, text: str) -> list[dict]:
    md = tmp_path / "tasks.md"
    md.write_text(text)
    return dispatch.parse_tasks(md)


def test_parse_reads_annotations_and_defaults(tmp_path: Path) -> None:
    tasks = {t["key"]: t for t in _parse(tmp_path, ANNOTATED_MD)}
    assert tasks["1.2"]["model"] == "opus"
    assert tasks["1.2"]["deps"] == ["1.1"]
    assert tasks["1.2"]["parallel"] is False
    assert tasks["1.2"]["serial_reason"].startswith("workspace_roots")
    # Undeclared model falls back to the routing default rather than being left unset.
    assert tasks["1.3"]["model"] == "sonnet"
    assert tasks["1.3"]["parallel"] is True


def test_unannotated_tasks_are_dispatchable_repo_change(tmp_path: Path) -> None:
    """The backward-compatibility guarantee: a tasks.md with no annotations behaves as before."""
    tasks = _parse(tmp_path, TASKS_MD)
    assert all(t["dispatchable"] for t in tasks)
    assert all(t["lane"] == "repo_change" for t in tasks)
    assert all(t["deps"] == [] for t in tasks)


def test_out_of_lane_tasks_get_no_work_order(tmp_path: Path) -> None:
    tasks = _parse(tmp_path, ANNOTATED_MD)
    paths = dispatch.emit_work_orders(tasks, "c", tmp_path / "out")
    assert [p.name for p in paths] == ["task-001.md", "task-002.md", "task-003.md"]
    assert not (tmp_path / "out" / "task-004.md").exists(), "destructive_ops task became claimable"


def test_task_ids_stay_positional_when_a_lane_is_skipped(tmp_path: Path) -> None:
    """Skipping an out-of-lane task must not renumber the rest — task IDs are quoted in issues.

    1.1 becomes destructive_ops here and 1.4 already is, so the two survivors keep the
    positional IDs 002 and 003 rather than sliding down to 001 and 002.
    """
    md = ANNOTATED_MD.replace("[lane: repo_change | wave: 0]", "[lane: destructive_ops | wave: 0]")
    paths = dispatch.emit_work_orders(_parse(tmp_path, md), "c", tmp_path / "out")
    assert [p.name for p in paths] == ["task-002.md", "task-003.md"]


def test_wave_depth_follows_the_dependency_graph(tmp_path: Path) -> None:
    waves = dispatch.compute_waves(_parse(tmp_path, ANNOTATED_MD))
    assert waves == {"1.1": 0, "1.2": 1, "1.3": 1, "1.4": 2}


def test_serial_task_releases_alone(tmp_path: Path) -> None:
    ready, held = dispatch.releasable(_parse(tmp_path, ANNOTATED_MD))
    assert [t["key"] for t in ready] == ["1.2"]
    assert [t["key"] for t, _ in held] == ["1.3"]


def test_dependency_on_an_out_of_lane_task_holds_the_dependent(tmp_path: Path) -> None:
    """The ocean-eventbridge-migration case: the import waits on a credential rotation run by a human."""
    md = """\
- [ ] 1.1 Rotate credentials  `[lane: destructive_ops | wave: 0]`
- [ ] 1.2 Import  `[deps: 1.1 | lane: repo_change | wave: 0]`
"""
    ready, held = dispatch.releasable(_parse(tmp_path, md))
    assert ready == []
    (task, blockers) = held[0]
    assert task["key"] == "1.2"
    assert "other queue" in blockers[0]


def test_done_tasks_are_not_released_and_unblock_dependents(tmp_path: Path) -> None:
    md = """\
- [x] 1.1 Merged  `[lane: repo_change]`
- [ ] 1.2 Next  `[deps: 1.1 | lane: repo_change]`
"""
    ready, held = dispatch.releasable(_parse(tmp_path, md))
    assert [t["key"] for t in ready] == ["1.2"]
    assert held == []


def test_validate_rejects_a_dependency_on_a_missing_task(tmp_path: Path) -> None:
    tasks = _parse(tmp_path, "- [ ] 1.1 A  `[deps: 9.9 | lane: repo_change]`\n")
    with pytest.raises(dispatch.DispatchError, match=r"9\.9"):
        dispatch.validate(tasks)


def test_validate_rejects_an_unjustified_serial_flag(tmp_path: Path) -> None:
    tasks = _parse(tmp_path, "- [ ] 1.1 A  `[parallel: no | lane: repo_change]`\n")
    with pytest.raises(dispatch.DispatchError, match="states no reason"):
        dispatch.validate(tasks)


def test_validate_rejects_an_unknown_lane(tmp_path: Path) -> None:
    tasks = _parse(tmp_path, "- [ ] 1.1 A  `[lane: yolo]`\n")
    with pytest.raises(dispatch.DispatchError, match="unknown lane"):
        dispatch.validate(tasks)


def test_validate_rejects_a_dependency_cycle(tmp_path: Path) -> None:
    md = """\
- [ ] 1.1 A  `[deps: 1.2 | lane: repo_change]`
- [ ] 1.2 B  `[deps: 1.1 | lane: repo_change]`
"""
    with pytest.raises(dispatch.DispatchError, match="cycle"):
        dispatch.validate(_parse(tmp_path, md))


def test_validate_rejects_a_task_scheduled_before_its_dependency(tmp_path: Path) -> None:
    md = """\
- [ ] 1.1 Late  `[lane: repo_change | wave: 3]`
- [ ] 1.2 Early  `[deps: 1.1 | lane: repo_change | wave: 1]`
"""
    with pytest.raises(dispatch.DispatchError, match="contradict"):
        dispatch.validate(_parse(tmp_path, md))


def test_validate_allows_an_ordered_chain_inside_one_wave(tmp_path: Path) -> None:
    """A wave is a coarser human grouping than dependency depth, so it may hold a chain.

    Requiring declared wave to equal graph depth rejected a correct tasks.md — the useful
    invariant is that nothing is scheduled ahead of what it depends on.
    """
    md = """\
- [ ] 2.1 Mapping  `[lane: repo_change | wave: 1]`
- [ ] 2.2 Publisher  `[deps: 2.1 | lane: repo_change | wave: 1]`
- [ ] 3.1 Guard  `[deps: 2.2 | lane: repo_change | wave: 2a]`
- [ ] 3.2 Convert  `[deps: 3.1 | lane: repo_change | wave: 2c]`
"""
    dispatch.validate(_parse(tmp_path, md))  # must not raise


def test_routing_section_only_appears_for_annotated_tasks(tmp_path: Path) -> None:
    """Goldens for an unannotated tasks.md must stay byte-identical."""
    annotated_dir = tmp_path / "a"
    plain_dir = tmp_path / "b"
    annotated_dir.mkdir()
    plain_dir.mkdir()

    annotated = _parse(annotated_dir, ANNOTATED_MD)
    plain = _parse(plain_dir, TASKS_MD)

    (with_routing,) = dispatch.emit_work_orders(annotated[1:2], "c", tmp_path / "outa")
    (without_routing,) = dispatch.emit_work_orders(plain[:1], "c", tmp_path / "outb")

    assert "## Routing" in with_routing.read_text()
    assert "## Routing" not in without_routing.read_text()


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
