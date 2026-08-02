"""Gate 5: Glue Script Logic.

Unit tests for the scaffold's own code — scripts/dispatch_tasks.py and
scripts/collect_handoffs.py — on hand-built fixtures.

Usage: uv run pytest tests/scaffold/cat5_glue_logic.py -v
"""

from pathlib import Path

import pytest

from ._scaffold import ROOT, load_script

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


# --- workflow.py: WORKFLOW.md's block is the source of truth, so something must read it --------
#
# The block sat in WORKFLOW.md for two revisions declaring itself "parsed by thin glue" while
# being invalid YAML. Nothing parsed it, so nothing noticed. These tests are the standing check
# that it stays parseable and internally consistent.

workflow = load_script("workflow.py")

MINIMAL = """\
# W

**Status:** v1.0.0

```yaml
ade_workflow:
  version: 1.0.0
  linear:
    team: DNA
    project: "P"
    statuses: [Todo, In Progress, Done]
    status_ownership:
      unstarted: sync
  state_resolution:
    order:
      - "any sub-issue status in [Todo, In Progress]": step=execute
  gates:
    G_ONE:
      blocks: [execute]
  lanes:
    repo_change:
      description: default
    destructive_ops:
      excluded_steps: [execute]
  routing:
    tiers: [sonnet, opus]
    default: {model: sonnet, max_tier: opus}
  steps:
    - id: execute
      actor: agent(sonnet)
      gate: G_ONE
      linear_status: In Progress -> Done
      next: done
    - id: done
      actor: human
```

```mermaid
flowchart TB
  E[execute<br/>gate: G_ONE] --> D[done]
```
"""


def _workflow_md(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "WORKFLOW.md"
    p.write_text(text)
    return p


def test_the_repos_own_workflow_block_parses() -> None:
    """The regression: `edit_protocol` held a `key: value` line that made the block invalid YAML."""
    block, _ = workflow.load(ROOT / "WORKFLOW.md")
    assert block["steps"], "WORKFLOW.md declares no steps"


def test_the_repos_own_workflow_block_is_clean() -> None:
    """`task check` runs this; asserting it here names the failure instead of just exiting 1."""
    block, text = workflow.load(ROOT / "WORKFLOW.md")
    errors = workflow.check_structure(block) + workflow.check_statuses(block) + workflow.check_projections(block, text)
    assert errors == [], "WORKFLOW.md has drifted:\n  - " + "\n  - ".join(errors)


def test_minimal_fixture_is_clean(tmp_path: Path) -> None:
    block, text = workflow.load(_workflow_md(tmp_path, MINIMAL))
    assert workflow.check_structure(block) == []
    assert workflow.check_statuses(block) == []
    assert workflow.check_projections(block, text) == []


def test_load_rejects_a_document_with_no_workflow_block(tmp_path: Path) -> None:
    with pytest.raises(workflow.WorkflowError, match="source of truth is missing"):
        workflow.load(_workflow_md(tmp_path, "# W\n\nno yaml here\n"))


def test_load_rejects_invalid_yaml(tmp_path: Path) -> None:
    """Exactly the shape that broke it: a plain-scalar list item containing `key: value`."""
    broken = MINIMAL.replace(
        "  version: 1.0.0", "  version: 1.0.0\n  notes:\n    - a thing: with a colon\n      and a continuation line"
    )
    with pytest.raises(workflow.WorkflowError, match="not valid YAML"):
        workflow.load(_workflow_md(tmp_path, broken))


def test_next_must_reference_a_real_step(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("next: done", "next: collect_when_wave_done")))
    errors = workflow.check_structure(block)
    assert any("collect_when_wave_done" in e for e in errors)


def test_lane_excluded_steps_must_reference_a_real_step(tmp_path: Path) -> None:
    """The live bug: `excluded_steps: [execute_in_orca]` named a step that never existed."""
    block, _ = workflow.load(
        _workflow_md(tmp_path, MINIMAL.replace("excluded_steps: [execute]", "excluded_steps: [execute_in_orca]"))
    )
    errors = workflow.check_structure(block)
    assert any("execute_in_orca" in e for e in errors)


def test_gate_reference_must_exist(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("gate: G_ONE", "gate: G_MISSING")))
    assert any("G_MISSING" in e for e in workflow.check_structure(block))


def test_gate_blocks_must_reference_a_real_step(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("blocks: [execute]", "blocks: [nope]")))
    assert any("nope" in e for e in workflow.check_structure(block))


def test_duplicate_step_ids_are_rejected(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("    - id: done", "    - id: execute")))
    assert any("duplicate step ids" in e for e in workflow.check_structure(block))


def test_actor_tier_must_be_a_declared_tier(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("actor: agent(sonnet)", "actor: agent(haiku)")))
    assert any("haiku" in e for e in workflow.check_structure(block))


def test_status_must_be_one_the_yaml_declares(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("In Progress -> Done", "In Progress -> Shipped")))
    assert any("Shipped" in e for e in workflow.check_statuses(block))


def test_undeclared_status_set_is_itself_an_error(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("    statuses: [Todo, In Progress, Done]\n", "")))
    assert any("linear.statuses is not declared" in e for e in workflow.check_statuses(block))


def test_diagram_may_not_omit_a_step(tmp_path: Path) -> None:
    block, text = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("--> D[done]", "--> D[finished]")))
    assert any("omits step 'done'" in e for e in workflow.check_projections(block, text))


def test_diagram_may_not_invent_a_gate(tmp_path: Path) -> None:
    block, text = workflow.load(
        _workflow_md(tmp_path, MINIMAL.replace("E[execute<br/>gate: G_ONE]", "E[execute<br/>gate: G_GHOST]"))
    )
    assert any("G_GHOST" in e for e in workflow.check_projections(block, text))


def test_header_version_must_match_the_yaml(tmp_path: Path) -> None:
    block, text = workflow.load(_workflow_md(tmp_path, MINIMAL.replace("**Status:** v1.0.0", "**Status:** v9.9.9")))
    assert any("stale" in e for e in workflow.check_projections(block, text))


def test_live_linear_check_skips_rather_than_fails_when_the_client_is_absent(tmp_path: Path) -> None:
    """A gate that fails because a machine lacks an optional tool teaches people to ignore it.

    `workflow:lint:linear` runs inside `task verify`, and the Linear CLI is optional per
    docs/contracts/consumes.md — so an absent client must skip loudly, not break the gate.
    """
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL))
    with pytest.raises(workflow.LinearUnavailable, match=r"unavailable|failed|parse"):
        workflow.check_linear_live(block)


def test_lint_exits_zero_when_the_live_check_is_skipped(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = _workflow_md(tmp_path, MINIMAL)
    assert workflow.lint(path, with_linear=True) == 0
    captured = capsys.readouterr()
    assert "SKIPPED" in captured.err, "a skipped live check must say so"
    assert "SKIPPED" in captured.out, "the summary must not claim the live check ran"
