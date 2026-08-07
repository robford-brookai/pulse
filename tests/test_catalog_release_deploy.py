"""The catalog release job is a deploy artifact, never a check step (catalog-authority 4.3).

Covers the `catalog-release` spec scenario "The check contract stays credential-free": the
`check` dependency closure never reaches `catalog:release`, and the deploy workflow is wired to
the shape D18 demands — push to main, `catalog/**` paths filter, `run:` steps resolving to
Taskfile targets (the cat4 contract), credentials supplied only as Actions secrets.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "catalog-release.yml"

RELEASE_TARGET = "catalog:release"


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


class TestCheckStaysCredentialFree:
    """Spec: The check contract stays credential-free."""

    def test_check_closure_excludes_the_release_target(self) -> None:
        closure = _closure(_taskfile(), "check")
        assert RELEASE_TARGET not in closure, (
            "`task check` reaches catalog:release — the check contract would need warehouse "
            "credentials on every runner (D18 forbids this)."
        )

    def test_check_closure_never_invokes_the_release_entrypoint(self) -> None:
        taskfile = _taskfile()
        for name in _closure(taskfile, "check"):
            for cmd in taskfile["tasks"][name].get("cmds") or []:
                if isinstance(cmd, str):
                    assert "catalog_release_cli" not in cmd, (
                        f"check-reachable target {name!r} invokes the release entrypoint directly"
                    )

    def test_main_workflow_never_mentions_the_release_target(self) -> None:
        main_yml = (_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text()
        assert RELEASE_TARGET not in main_yml


class TestReleaseTarget:
    def test_release_target_exists_and_runs_the_entrypoint(self) -> None:
        taskfile = _taskfile()
        assert RELEASE_TARGET in taskfile["tasks"]
        cmds = [cmd for cmd in taskfile["tasks"][RELEASE_TARGET]["cmds"] if isinstance(cmd, str)]
        assert any("pulse_core.catalog_release_cli" in cmd for cmd in cmds)

    def test_apply_is_opt_in_via_the_apply_variable(self) -> None:
        """The linear:sync posture: plan by default, `APPLY=1` is the only way to mutate."""
        cmds = [cmd for cmd in _taskfile()["tasks"][RELEASE_TARGET]["cmds"] if isinstance(cmd, str)]
        entrypoint = next(cmd for cmd in cmds if "catalog_release_cli" in cmd)
        assert "{{if .APPLY}}--apply{{end}}" in entrypoint


class TestReleaseWorkflow:
    def test_triggers_on_push_to_main_with_a_catalog_paths_filter(self) -> None:
        trigger = _trigger(_workflow())
        assert set(trigger) == {"push"}, "the release job runs on merge to main only — no other trigger"
        assert trigger["push"]["branches"] == ["main"]
        assert trigger["push"]["paths"] == ["catalog/**"]

    def test_every_run_step_resolves_to_the_release_target(self) -> None:
        steps = _run_steps(_workflow())
        assert steps, "the release workflow has no run steps"
        assert any(f"task {RELEASE_TARGET}" in step and "APPLY=1" in step for step in steps)

    def test_credentials_come_from_actions_secrets_only(self) -> None:
        text = _WORKFLOW.read_text()
        for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"):
            assert f"${{{{ secrets.{name} }}}}" in text, f"{name} must come from an Actions secret"
        assert "PASSWORD:" in text
        assert "hunter2" not in text  # no literal credential ever
