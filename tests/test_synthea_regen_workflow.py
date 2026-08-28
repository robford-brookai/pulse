"""The synthea regen workflow is regeneration infrastructure, never a check step.

Covers the `synthetic-population` spec requirement "Regeneration is a task, never part of the
check gate": the `check` dependency closure never reaches `synthea:regen` (so `task check`
stays green on machines without Java), and the workflow is wired to the shape the design
demands — workflow_dispatch plus schedule, its run step resolving to the Taskfile target (the
cat4 contract), and the population artifact uploaded for the staging loader. Same posture and
shape as test_catalog_release_deploy.py.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "synthea-regen.yml"

REGEN_TARGET = "synthea:regen"


def _taskfile() -> dict:
    return yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())


def _closure(taskfile: dict, root: str) -> set[str]:
    """Every Taskfile target reachable from `root` through `task:` refs."""
    tasks = taskfile["tasks"]
    seen: set[str] = set()
    frontier = [root]
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        for cmd in tasks[name].get("cmds") or []:
            if isinstance(cmd, dict) and cmd.get("task") in tasks:
                frontier.append(cmd["task"])
    return seen


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text())


def _trigger(workflow: dict) -> dict:
    # yaml parses the bare key `on` as boolean True.
    return workflow.get("on") or workflow[True]


def _run_steps(workflow: dict) -> list[str]:
    return [
        str(step["run"])
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if isinstance(step, dict) and "run" in step
    ]


class TestCheckStaysJavaFree:
    """Spec scenario: Check stays Java-free."""

    def test_check_closure_never_reaches_regen(self) -> None:
        taskfile = _taskfile()
        closure = _closure(taskfile, "check")
        assert REGEN_TARGET in taskfile["tasks"], f"{REGEN_TARGET} is not defined"
        assert REGEN_TARGET not in closure, "`task check` must stay green on runners without Java"

    def test_no_check_command_invokes_java_or_the_regen_module(self) -> None:
        taskfile = _taskfile()
        commands = [
            cmd
            for name in _closure(taskfile, "check")
            for cmd in taskfile["tasks"][name].get("cmds") or []
            if isinstance(cmd, str)
        ]
        joined = "\n".join(commands)
        assert "java" not in joined
        assert "synthea_seed.regen" not in joined


class TestRegenWorkflowShape:
    """Spec scenario: Staging regen is invocable on demand."""

    def test_workflow_parses(self) -> None:
        assert _workflow()["jobs"], "workflow must define at least one job"

    def test_triggers_are_dispatch_and_schedule_only(self) -> None:
        trigger = _trigger(_workflow())
        assert set(trigger) == {"workflow_dispatch", "schedule"}
        assert trigger["schedule"], "schedule must carry at least one cron entry"

    def test_never_triggered_by_push_or_pull_request(self) -> None:
        trigger = _trigger(_workflow())
        assert "push" not in trigger and "pull_request" not in trigger, (
            "regeneration is scheduled/dispatched infrastructure, never per-PR CI"
        )

    def test_single_run_step_is_the_staging_regen_target(self) -> None:
        steps = _run_steps(_workflow())
        assert steps == [f"task {REGEN_TARGET} PROFILE=staging"]

    def test_workflow_installs_java_for_the_regen_step(self) -> None:
        uses = [
            str(step.get("uses", ""))
            for job in _workflow()["jobs"].values()
            for step in job["steps"]
            if isinstance(step, dict)
        ]
        assert any(entry.startswith("actions/setup-java@") for entry in uses), (
            "Java is the regen prerequisite; the workflow must install it itself"
        )

    def test_population_artifact_is_uploaded(self) -> None:
        upload_steps = [
            step
            for job in _workflow()["jobs"].values()
            for step in job["steps"]
            if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        assert len(upload_steps) == 1, "the staging loader consumes exactly one population artifact"
        with_block = upload_steps[0]["with"]
        assert with_block["path"] == "packages/synthea-seed/output/staging"
        assert with_block["if-no-files-found"] == "error"


class TestMainWorkflowUntouched:
    def test_main_quality_job_runs_exactly_task_check(self) -> None:
        main = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text())
        quality_runs = [
            str(step["run"]) for step in main["jobs"]["quality"]["steps"] if isinstance(step, dict) and "run" in step
        ]
        assert quality_runs == ["task check"]
