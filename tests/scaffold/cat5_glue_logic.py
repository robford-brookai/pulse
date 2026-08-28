"""Gate 5: Glue Script Logic.

Unit tests for the scaffold's own code — scripts/dispatch_tasks.py and
scripts/collect_handoffs.py — on hand-built fixtures.

Usage: uv run pytest tests/scaffold/cat5_glue_logic.py -v
"""

import json
import subprocess
from datetime import date
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


def _git_repo_with_ignore(tmp_path: Path, pattern: str) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    (tmp_path / ".gitignore").write_text(pattern + "\n")
    summary = tmp_path / "handoffs" / "c" / "SUMMARY.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("# SUMMARY\n")
    return summary


def test_collect_detects_an_ignored_summary(tmp_path: Path) -> None:
    """The regression this guards: a directory-level `handoffs/` ignore silently loses the
    receipt record — the escalation ladder's own evidence never enters the repo."""
    assert collect.summary_is_ignored(_git_repo_with_ignore(tmp_path, "handoffs/"))


def test_collect_accepts_a_trackable_summary(tmp_path: Path) -> None:
    assert not collect.summary_is_ignored(
        _git_repo_with_ignore(tmp_path, "handoffs/**\n!handoffs/*/\n!handoffs/*/SUMMARY.md")
    )


def test_summary_check_outside_a_repo_is_not_an_error(tmp_path: Path) -> None:
    """cat9 collects into plain temp dirs; no repo means nothing can be ignored."""
    summary = tmp_path / "handoffs" / "c" / "SUMMARY.md"
    summary.parent.mkdir(parents=True)
    assert not collect.summary_is_ignored(summary)


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


# --- checkoff_tasks.py: merged PRs flip their own boxes, nobody hand-types the commit -----------
#
# The first real change put 25 hand-typed `chore: check off` commits on main. Each was
# load-bearing (dispatch reads checked boxes to release waves), none was reviewable content.
# checkoff derives the flips from main's own history instead.

checkoff = load_script("checkoff_tasks.py")

CHECKOFF_MD = """\
# Tasks

## 1. Wave 0

- [ ] 1.1 First task
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
- [x] 1.2 Already recorded
- [ ] 2.3 Later task
"""


def test_subject_ids_follow_the_convention() -> None:
    """The `(X.Y[, TEAM-n])` convention, as observed on the ocean run's actual merge subjects."""
    cases = {
        "fix(ocean): set AWS_DEFAULT_REGION (6.7) (#65)": {"6.7"},
        "test(ocean): record equivalence — EQUIVALENT (8.2, DNA-774) (#63)": {"8.2"},
        "feat(catalog): subscribe event-store (5.8, DNA-783) (#54)": {"5.8"},
        "chore: check off 6.7 and 10.1": set(),  # checkoff's own commits never re-match
        "feat(zcc-connector): publish through EventBridge, not Redpanda (#31)": set(),
        "3.1 [DNA-738] graph-projection: sequence guard (#33)": set(),  # bare prefix, no parens
    }
    for subject, expected in cases.items():
        assert checkoff.subject_task_ids(subject) == expected, subject


def test_flip_checks_exactly_the_merged_boxes() -> None:
    new, flipped, unknown = checkoff.flip(CHECKOFF_MD, {"1.1"})
    assert flipped == ["1.1"]
    assert unknown == []
    assert "- [x] 1.1 First task" in new
    assert "- [ ] 2.3 Later task" in new, "an unmerged task must stay unchecked"


def test_flip_touches_only_checkbox_state() -> None:
    new, _, _ = checkoff.flip(CHECKOFF_MD, {"1.1"})
    diff = [(a, b) for a, b in zip(CHECKOFF_MD.splitlines(), new.splitlines(), strict=True) if a != b]
    assert all(a.replace("[ ]", "[x]", 1) == b for a, b in diff), "flip changed more than a checkbox"
    assert len(CHECKOFF_MD.splitlines()) == len(new.splitlines())


def test_flip_is_idempotent() -> None:
    """An already-checked task is a no-op, so rerunning after new merges is always safe."""
    new, flipped, _ = checkoff.flip(CHECKOFF_MD, {"1.2"})
    assert flipped == []
    assert new == CHECKOFF_MD


def test_flip_refuses_unknown_ids() -> None:
    """A subject referencing a task this change does not have is a defect, not a silent skip."""
    _, flipped, unknown = checkoff.flip(CHECKOFF_MD, {"9.9"})
    assert unknown == ["9.9"]
    assert flipped == []


def test_explicit_commits_bypass_the_history_scan(tmp_path: Path) -> None:
    """--commit <sha>: the coordinator names the merge it just saw, nothing else is consulted."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607

    def commit(subject: str) -> str:
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.email=t@test.invalid",
                "-c",
                "user.name=T",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                subject,
            ],
            check=True,
        )
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    wanted = commit("feat: the one Rob merged (1.1, DNA-900)")
    commit("feat: a different merge (2.3)")

    sources = checkoff.sources_for_commits([wanted], cwd=tmp_path)
    assert set(sources) == {"1.1"}, "only the named commit's ids may be recorded"


def test_checkoff_report_prefills_the_next_command() -> None:
    report = checkoff.next_steps("my-change")
    assert "task dispatch CHANGE=my-change" in report, "the follow-up must be copy-runnable"


def test_v2_1_replan_is_wired() -> None:
    """v2.1.0 regression: replan exists, execute reaches it, and it flows back through sync."""
    block, _ = workflow.load(ROOT / "WORKFLOW.md")
    steps = {s["id"]: s for s in block["steps"]}
    assert "replan" in steps, "the replan step is gone"
    assert steps["execute"]["next"].get("plan_amendment") == "replan"
    assert steps["replan"]["next"].get("pass") == "sync_linear"
    assert "G_MECE" in str(steps["replan"].get("gate", ""))


def test_state_resolution_reads_no_machine_local_state() -> None:
    """v2.1.0 regression: every resolution rule must be computable on a fresh clone.

    v2.0.3 keyed three rules on gitignored paths (work_orders/ staleness, an untracked
    SUMMARY.md, local worktree existence), so two machines could resolve the same change to
    different steps. Comments in the block may still discuss those paths; the rules may not.
    """
    block, _ = workflow.load(ROOT / "WORKFLOW.md")
    rules = [
        condition for entry in block["state_resolution"]["order"] if isinstance(entry, dict) for condition in entry
    ]
    offenders = [r for r in rules if "work_orders/" in r or "worktree" in r.lower()]
    assert offenders == [], f"resolution rules read machine-local state: {offenders}"
    summary_rules = [r for r in rules if "SUMMARY.md absent" in r]
    assert all("tracked" in r for r in summary_rules), "the collect rule must read the tracked tree"


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


# --- linear_sync: the repo is the record, Linear is a one-directional projection ---------------
#
# The status rules are the load-bearing part. Sync owns the unstarted band and nothing else; a
# sync that writes `In Progress` steals a band from the agents that own it, and the damage reads
# as an agent misbehaving rather than a tool overreaching.

linear_sync = load_script("linear_sync.py")

SYNC_TASKS_MD = """\
# Tasks

## 1. Group

- [ ] 1.1 Rotate credentials  `[lane: destructive_ops]`
- [ ] 1.2 Import `robford-brookai/ocean` at `7bc9d2c`  `[lane: repo_change]`
- [ ] 1.3 Plain task  `[lane: repo_change]`
"""


def _synced(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    tasks = _parse(tmp_path, SYNC_TASKS_MD)
    orders = tmp_path / "wo" / "c"
    orders.mkdir(parents=True)
    for task in tasks:
        (orders / f"{task['task_id']}.md").write_text(f"body for {task['key']}\n")
    return tasks, linear_sync.desired_subissues("c", tasks, tmp_path / "wo")


def test_out_of_lane_tasks_are_not_synced(tmp_path: Path) -> None:
    """destructive_ops runs on the Open Engine queue, which has its own status vocabulary."""
    _, desired = _synced(tmp_path)
    assert [d["key"] for d in desired] == ["1.2", "1.3"]


def test_issue_title_keeps_inline_code_and_does_not_repeat_the_key(tmp_path: Path) -> None:
    """Splitting the title at the first backtick truncated it to one word."""
    _, desired = _synced(tmp_path)
    title = next(d["title"] for d in desired if d["key"] == "1.2")
    assert title == "1.2 Import `robford-brookai/ocean` at `7bc9d2c`"
    assert not title.startswith("1.2 1.2")


def test_description_is_the_work_order_body(tmp_path: Path) -> None:
    _, desired = _synced(tmp_path)
    assert desired[0]["description"] == "body for 1.2\n"


def test_sync_refuses_when_the_work_order_is_missing(tmp_path: Path) -> None:
    tasks = _parse(tmp_path, SYNC_TASKS_MD)
    with pytest.raises(linear_sync.SyncError, match="task dispatch"):
        linear_sync.desired_subissues("c", tasks, tmp_path / "absent")


def test_plan_creates_parent_and_children_on_an_empty_workspace(tmp_path: Path) -> None:
    _, desired = _synced(tmp_path)
    ops = linear_sync.plan(desired, {}, parent_exists=False, change="c")
    assert [o["kind"] for o in ops] == ["create_parent", "create_sub", "create_sub"]


def test_plan_is_a_no_op_when_linear_already_matches(tmp_path: Path) -> None:
    _, desired = _synced(tmp_path)
    existing = {
        d["key"]: {"identifier": f"DNA-{i}", "title": d["title"], "description": d["description"], "status": "Todo"}
        for i, d in enumerate(desired)
    }
    assert linear_sync.plan(desired, existing, parent_exists=True, change="c") == []


def test_plan_updates_a_sub_issue_whose_description_drifted(tmp_path: Path) -> None:
    """A sub-issue edited by hand in Linear is drift; the file wins."""
    _, desired = _synced(tmp_path)
    existing = {
        desired[0]["key"]: {
            "identifier": "DNA-1",
            "title": desired[0]["title"],
            "description": "someone edited this in the UI",
            "status": "Todo",
        }
    }
    ops = linear_sync.plan(desired, existing, parent_exists=True, change="c")
    assert {"kind": "update_sub", "key": "1.2", "id": "DNA-1"} in ops


def test_plan_heals_triage_but_touches_no_other_status(tmp_path: Path) -> None:
    _, desired = _synced(tmp_path)

    def existing_with(status: str) -> dict:
        return {
            desired[0]["key"]: {
                "identifier": "DNA-1",
                "title": desired[0]["title"],
                "description": desired[0]["description"],
                "status": status,
            }
        }

    healed = linear_sync.plan(desired, existing_with("Triage"), parent_exists=True, change="c")
    assert any(o["kind"] == "heal_status" for o in healed)

    for owned in ("In Progress", "Blocked", "In Review", "Done", "Canceled"):
        ops = linear_sync.plan(desired, existing_with(owned), parent_exists=True, change="c")
        assert not any(o["kind"] == "heal_status" for o in ops), f"sync tried to move a {owned} issue"


def test_plan_reports_orphans_without_deleting_them(tmp_path: Path) -> None:
    """A task removed from tasks.md leaves an issue behind; say so, do not silently close it."""
    _, desired = _synced(tmp_path)
    existing = {"9.9": {"identifier": "DNA-99", "title": "9.9 gone", "description": "", "status": "Todo"}}
    ops = linear_sync.plan(desired, existing, parent_exists=True, change="c")
    orphans = [o for o in ops if o["kind"] == "orphan"]
    assert [o["key"] for o in orphans] == ["9.9"]


def test_status_guard_rejects_a_write_outside_the_unstarted_band() -> None:
    statuses = ["Triage", "Todo", "In Progress", "Done"]
    linear_sync.assert_status_writes_are_legal([{"kind": "create_sub", "state": "Todo"}], statuses)
    with pytest.raises(linear_sync.SyncError, match="does not own"):
        linear_sync.assert_status_writes_are_legal([{"kind": "create_sub", "state": "In Progress"}], statuses)


# --- linear_sync id write-back: the ONE sanctioned reverse edge ---------------------------------
#
# The id is the one fact Linear mints. The first real change spent whole commits hand-copying
# `[DNA-nnn]` tokens into tasks.md; the write-back inserts them on create, and nothing else ever
# flows Linear -> repo.

WRITEBACK_MD = """\
# Tasks

- [ ] 1.1 New task  `[lane: repo_change]`
- [x] 1.2 [DNA-734] Old task with an id  `[lane: repo_change]`
- [ ] 2.1 Untouched sibling  `[lane: repo_change]`
"""


def test_write_back_inserts_the_id_after_the_task_key() -> None:
    new, written = linear_sync.write_back_ids(WRITEBACK_MD, {"1.1": "DNA-812"})
    assert written == ["1.1"]
    assert "- [ ] 1.1 [DNA-812] New task" in new


def test_write_back_never_rewrites_an_existing_token() -> None:
    new, written = linear_sync.write_back_ids(WRITEBACK_MD, {"1.2": "DNA-999"})
    assert written == []
    assert "[DNA-734]" in new
    assert "DNA-999" not in new


def test_write_back_touches_only_the_written_line() -> None:
    new, _ = linear_sync.write_back_ids(WRITEBACK_MD, {"1.1": "DNA-812"})
    old_lines, new_lines = WRITEBACK_MD.splitlines(), new.splitlines()
    changed = [(a, b) for a, b in zip(old_lines, new_lines, strict=True) if a != b]
    assert len(changed) == 1
    assert changed[0][1] == changed[0][0].replace("1.1 ", "1.1 [DNA-812] ", 1)


class _FakeClient:
    """Answers create mutations with minted identifiers; fails on demand."""

    def __init__(self, fail_on_key: str | None = None) -> None:
        self.minted = 0
        self._fail_on_key = fail_on_key

    def query(self, document: str, variables: dict) -> dict:
        title = variables.get("input", {}).get("title", "")
        if self._fail_on_key and title.startswith(self._fail_on_key):
            raise linear_sync.SyncError("boom")
        self.minted += 1
        return {
            "issueCreate": {"success": True, "issue": {"id": f"uuid-{self.minted}", "identifier": f"DNA-{self.minted}"}}
        }


def _apply_ctx() -> dict:
    return {"team_id": "t", "todo_state_id": "s", "project_id": None, "states": {}}


def test_apply_reports_created_identifiers_for_the_write_back(tmp_path: Path) -> None:
    _, desired = _synced(tmp_path)
    ops = linear_sync.plan(desired, {}, parent_exists=False, change="c")
    created: dict[str, str] = {}
    linear_sync.apply_plan(_FakeClient(), ops, desired, _apply_ctx(), "c", created)
    assert set(created) == {"1.2", "1.3"}, "every created sub-issue must surface its identifier"


def test_a_failed_create_writes_no_phantom_id(tmp_path: Path) -> None:
    """Partial apply: identifiers minted before the failure survive; the failed one never appears."""
    _, desired = _synced(tmp_path)
    ops = linear_sync.plan(desired, {}, parent_exists=False, change="c")
    created: dict[str, str] = {}
    with pytest.raises(linear_sync.SyncError):
        linear_sync.apply_plan(_FakeClient(fail_on_key="1.3"), ops, desired, _apply_ctx(), "c", created)
    assert "1.3" not in created
    assert "1.2" in created, "an id minted before the failure must not be lost"


def test_dry_run_plan_names_the_pending_write_back(tmp_path: Path) -> None:
    _, desired = _synced(tmp_path)
    ops = linear_sync.plan(desired, {}, parent_exists=False, change="c")
    rendered = linear_sync.render_plan(ops, [])
    assert "written back" in rendered.lower(), "the dry run must say ids will be written back on apply"


def test_target_comes_from_workflow_md_not_the_api_key(tmp_path: Path) -> None:
    block, _ = workflow.load(_workflow_md(tmp_path, MINIMAL))
    assert linear_sync._target(block) == ("DNA", "P")


def test_target_refuses_when_no_team_is_declared(tmp_path: Path) -> None:
    with pytest.raises(linear_sync.SyncError, match="no team"):
        linear_sync._target({"linear": {"project": "P"}})


def test_apply_without_a_key_is_an_error_not_a_silent_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    assert linear_sync._api_key(require=False) == ""
    with pytest.raises(linear_sync.SyncError, match="LINEAR_API_KEY"):
        linear_sync._api_key(require=True)


# --- collect_handoffs: a missing receipt must be loud ------------------------------------------
#
# task-002 imported 193 commits of ocean history and stopped without a HANDOFF.md. collect
# skipped it silently, so a worktree that had done real work looked identical to one that had
# not started. AGENTS.md requires the receipt; nothing enforced it.


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=g@test.invalid", "-c", "user.name=G", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _repo_with_worktree(tmp_path: Path, *, commit_in_worktree: bool, handoff: bool) -> tuple[Path, Path]:
    """A real git repo plus a linked worktree — the delinquency check reads git, not the filesystem."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    (repo / "seed.txt").write_text("seed\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "base", cwd=repo)

    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "task", str(wt), cwd=repo)
    if commit_in_worktree:
        (wt / "work.txt").write_text("did the work\n")
        _git("add", "-A", cwd=wt)
        _git("commit", "-qm", "the work", cwd=wt)
    if handoff:
        (wt / "HANDOFF.md").write_text("# HANDOFF\n")
    return repo, wt


def test_commits_without_a_handoff_are_delinquent(tmp_path: Path) -> None:
    repo, wt = _repo_with_worktree(tmp_path, commit_in_worktree=True, handoff=False)
    found = collect.delinquent_worktrees([wt], "main", repo)
    assert [(p.name, n) for p, n in found] == [("wt", 1)]


def test_a_worktree_that_has_not_started_is_not_delinquent(tmp_path: Path) -> None:
    """No commits and no HANDOFF is 'not started', which is the case the old code conflated."""
    repo, wt = _repo_with_worktree(tmp_path, commit_in_worktree=False, handoff=False)
    assert collect.delinquent_worktrees([wt], "main", repo) == []


def test_commits_with_a_handoff_are_fine(tmp_path: Path) -> None:
    repo, wt = _repo_with_worktree(tmp_path, commit_in_worktree=True, handoff=True)
    assert collect.delinquent_worktrees([wt], "main", repo) == []


def test_the_repo_root_is_never_its_own_delinquent(tmp_path: Path) -> None:
    """`git worktree list` includes the main worktree, which never carries a HANDOFF."""
    repo, _ = _repo_with_worktree(tmp_path, commit_in_worktree=False, handoff=False)
    assert collect.delinquent_worktrees([repo], "main", repo) == []


def test_an_uninspectable_directory_is_not_reported_as_delinquent(tmp_path: Path) -> None:
    """Cannot-tell must not become an accusation — this is what keeps the cat9 fixtures working."""
    plain = tmp_path / "not-a-worktree"
    plain.mkdir()
    assert collect.commits_ahead(plain, "main") is None
    assert collect.delinquent_worktrees([plain], "main", tmp_path) == []


def test_commits_ahead_survives_an_unresolvable_base_ref(tmp_path: Path) -> None:
    repo, wt = _repo_with_worktree(tmp_path, commit_in_worktree=True, handoff=False)
    assert collect.commits_ahead(wt, "origin/nonexistent") is None
    assert collect.delinquent_worktrees([wt], "origin/nonexistent", repo) == []


# --- dispatch: G_HARDENING is enforced, not just declared --------------------------------------
#
# WORKFLOW.md said `G_HARDENING blocks: [execute]` and nothing checked it. Two worktrees launched
# straight through, and the audit that followed (DNA-777) found Orca spawning every agent with
# --dangerously-skip-permissions.

GOOD_RECEIPT = {
    "audited": "2026-08-02",
    "issue": "https://linear.app/x/DNA-777",
    "checks": {"H1": "pass", "H2": "pass", "H3": "pass", "H4": "pass"},
}


def _receipt(tmp_path: Path, payload: dict | str) -> Path:
    p = tmp_path / "hardening-receipt.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return p


def _profile(tmp_path: Path, args: dict) -> Path:
    p = tmp_path / "orca-data.json"
    p.write_text(json.dumps({"settings": {"agentDefaultArgs": args}}))
    return p


def test_a_clean_receipt_permits_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {"claude": "--verbose"}))
    assert dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, GOOD_RECEIPT)) == []


def test_a_missing_receipt_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), tmp_path / "absent.json")
    assert any("no G_HARDENING receipt" in p for p in problems)


def test_a_failing_adoption_check_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    bad = {**GOOD_RECEIPT, "checks": {**GOOD_RECEIPT["checks"], "H2": "fail", "H3": "unverified"}}
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, bad))
    assert any("H2=fail" in p and "H3=unverified" in p for p in problems)


def test_unverified_is_not_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H1 and H3 came back 'unverified', which must block exactly as 'fail' does."""
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    receipt = {**GOOD_RECEIPT, "checks": {**GOOD_RECEIPT["checks"], "H1": "unverified"}}
    assert dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, receipt))


def test_a_stale_receipt_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    problems = dispatch.hardening_problems("claude", date(2027, 1, 1), _receipt(tmp_path, GOOD_RECEIPT))
    assert any("days old" in p for p in problems)


def test_a_live_bypass_blocks_even_with_a_clean_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The receipt records what was true when someone looked. This setting re-arms every worktree."""
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {"claude": "--dangerously-skip-permissions"}))
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, GOOD_RECEIPT))
    assert any("H4 live" in p for p in problems)


@pytest.mark.parametrize(
    "arg",
    [
        "--yolo",
        "--auto-approve true",
        "--dangerously-bypass-approvals-and-sandbox",
        "--trust-all-tools",
        "--yes-always",
        "--dangerously-allow-all",
        "--unrestricted",
        "--permission-mode bypassPermissions",
    ],
)
def test_every_shipped_bypass_default_is_recognised(arg: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Orca ships a bypass default for all 24 agent types, not just claude."""
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {"someagent": arg}))
    assert dispatch.live_agent_bypass("someagent") == arg


def test_an_unreadable_profile_is_not_treated_as_safe_or_as_a_bypass(tmp_path: Path) -> None:
    """Absence of the profile is not evidence of safety, but it is not grounds to block either."""
    assert dispatch.live_agent_bypass("claude", tmp_path / "nothing.json") is None
    assert dispatch.live_agent_bypass("claude", _receipt(tmp_path, "not json")) is None


def test_a_corrupt_receipt_blocks_rather_than_passing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, "{ broken"))
    assert any("unreadable" in p for p in problems)


# --- G_HARDENING exceptions --------------------------------------------------------------------
#
# Some checks cannot pass without giving up a feature that is genuinely wanted: H2 asks for a
# localhost-only daemon and the phone client needs it reachable. Without a first-class exception
# those go through --skip-hardening on every dispatch, which turns a deliberate decision into
# noise nobody reads.

ACCEPTED = {
    "audited": "2026-08-02",
    "issue": "https://linear.app/x/DNA-777",
    "checks": {"H1": "pass", "H2": "accepted", "H3": "pass", "H4": "pass"},
    "exceptions": {"H2": {"justification": "phone client needs LAN reach", "review_by": "2026-11-02"}},
}


def test_a_justified_unexpired_exception_permits_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    assert dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, ACCEPTED)) == []


def test_an_exception_without_a_justification_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    bad = {**ACCEPTED, "exceptions": {"H2": {"review_by": "2026-11-02"}}}
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, bad))
    assert any("no justification" in p for p in problems)


def test_an_exception_with_no_review_date_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception that never expires is just a silent failure with better manners."""
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    bad = {**ACCEPTED, "exceptions": {"H2": {"justification": "because"}}}
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, bad))
    assert any("must expire" in p for p in problems)


def test_a_lapsed_exception_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {}))
    problems = dispatch.hardening_problems("claude", date(2027, 1, 1), _receipt(tmp_path, ACCEPTED))
    assert any("lapsed" in p for p in problems)


def test_accepted_does_not_launder_a_live_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H4 is read from the live setting, so an exception cannot talk it into being safe."""
    monkeypatch.setattr(dispatch, "ORCA_PROFILE", _profile(tmp_path, {"claude": "--yolo"}))
    receipt = {
        **ACCEPTED,
        "checks": {**ACCEPTED["checks"], "H4": "accepted"},
        "exceptions": {
            **ACCEPTED["exceptions"],
            "H4": {"justification": "we like living dangerously", "review_by": "2099-01-01"},
        },
    }
    problems = dispatch.hardening_problems("claude", date(2026, 8, 2), _receipt(tmp_path, receipt))
    assert any("H4 live" in p for p in problems)
