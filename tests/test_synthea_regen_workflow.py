"""The synthea regen workflow is regeneration infrastructure, never a check step.

Covers the `synthetic-population` spec requirement "Regeneration is a task, never part of the
check gate": the `check` dependency closure never reaches `synthea:regen` (so `task check`
stays green on machines without Java), and the workflow is wired to the shape the design
demands — workflow_dispatch plus schedule, its run step resolving to the Taskfile target (the
cat4 contract), and the population artifact uploaded for the staging loader. Same posture and
shape as test_catalog_release_deploy.py.

These assertions are shape only. They pass against a workflow that has never executed, which
is exactly how five scheduled runs failed unnoticed (docs/ci-lessons.md, 2026-09-08) — the
gate that closes that hole is
cat4_ci_contract.py::test_scheduled_regen_profiles_have_a_committed_manifest.
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


def _upload_steps(workflow: dict) -> dict[str, dict]:
    """Every upload-artifact step, keyed on the artifact name it publishes."""
    return {
        step["with"]["name"]: step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/upload-artifact@")
    }


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
        """One run step, resolving to the Taskfile target — the cat4 contract holds by shape."""
        steps = _run_steps(_workflow())
        assert len(steps) == 1
        assert steps[0].startswith(f"task {REGEN_TARGET} PROFILE=staging")

    def test_repin_is_a_dispatch_input_that_defaults_to_verifying(self) -> None:
        """The manifest is authored here, but only when a human asks for it by name."""
        dispatch = _trigger(_workflow())["workflow_dispatch"]
        repin = dispatch["inputs"]["repin"]
        assert repin["type"] == "boolean"
        assert repin["default"] is False, "a dispatch with no answer must verify, never re-pin"

    def test_the_run_step_passes_repin_only_when_the_input_is_set(self) -> None:
        """A scheduled run leaves `inputs.repin` unset, so the expression contributes nothing."""
        step = _run_steps(_workflow())[0]
        assert "REPIN=1" in step, "the repin path must reach the Taskfile target"
        assert "inputs.repin" in step, "REPIN=1 must be gated on the dispatch input, not unconditional"

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
        population = _upload_steps(_workflow())["synthea-staging-population"]
        assert population["with"]["path"] == "packages/synthea-seed/output/staging"
        assert population["with"]["if-no-files-found"] == "error"
        assert "if" not in population, "the population artifact is the product of every run"

    def test_a_repin_run_uploads_the_manifest_for_review(self) -> None:
        """The manifest leaves the runner as an artifact — never as a commit the job pushes."""
        manifest = _upload_steps(_workflow())["synthea-staging-manifest"]
        assert manifest["with"]["path"] == "packages/synthea-seed/manifests/staging.manifest.json"
        assert manifest["with"]["if-no-files-found"] == "error"
        assert "inputs.repin" in str(manifest["if"]), "the manifest upload belongs to the re-pin path only"

    def test_the_job_never_writes_back_to_the_branch(self) -> None:
        """A re-pin lands through review, never through a push from the runner.

        The single-run-step assertion above already rules out a shell commit; this rules out
        the action-shaped way of doing the same thing.
        """
        steps = _workflow()["jobs"]["regen-staging"]["steps"]
        uses = [str(step.get("uses", "")) for step in steps if isinstance(step, dict)]
        forbidden = ("auto-commit", "create-pull-request", "push-action")
        assert not [entry for entry in uses if any(marker in entry for marker in forbidden)]

    def test_the_pinned_jar_is_cached_across_runs(self) -> None:
        """~500 MB re-downloaded weekly; the checksum in ensure_jar is what keeps it honest."""
        steps = _workflow()["jobs"]["regen-staging"]["steps"]
        cache = next(
            step for step in steps if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/cache@")
        )
        assert cache["with"]["path"] == "packages/synthea-seed/.jars"
        assert "synthea-pin.yaml" in cache["with"]["key"], "a pin edit must miss the cache by construction"

    def test_the_job_is_bounded_by_a_timeout(self) -> None:
        assert _workflow()["jobs"]["regen-staging"]["timeout-minutes"] > 0


class TestMainWorkflowUntouched:
    def test_main_quality_job_never_runs_regen(self) -> None:
        """The quality job may gain legitimate steps of its own (critical-path-verification task
        1.2 added Postgres provisioning), but `synthea:regen` must never be one of them — that
        would put a Java-dependent, hours-long generation on the fast gate this module's
        docstring says regeneration must stay off of. `task check` itself stays the actual check
        step; the CI contract for what that resolves to is cat4_ci_contract.py's job."""
        main = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text())
        quality_runs = [
            str(step["run"]) for step in main["jobs"]["quality"]["steps"] if isinstance(step, dict) and "run" in step
        ]
        assert "task check" in quality_runs
        assert REGEN_TARGET not in "\n".join(quality_runs)
