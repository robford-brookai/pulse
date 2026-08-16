"""The ledger's deploy artifacts are never a check step (task 4.5's serving-layer wiring).

Modeled on `test_catalog_release_deploy.py`, which computes the same reachable-from-check set for
`catalog:release`: `ledger:image`, `ledger:migrate`, and `ledger:deploy` all need something `check`
must never depend on (a Docker daemon, a real Postgres, or registry/cluster credentials), so none
of them may be reachable from `check` through Taskfile `task:` refs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]

LEDGER_TARGETS = ("ledger:image", "ledger:migrate", "ledger:deploy")


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


class TestCheckStaysCredentialFree:
    """`task check` must never reach a target needing Docker, a live database, or credentials."""

    def test_check_closure_excludes_every_ledger_deploy_target(self) -> None:
        closure = _closure(_taskfile(), "check")
        for target in LEDGER_TARGETS:
            assert target not in closure, (
                f"`task check` reaches {target!r} — the check contract would need Docker/DB/cluster "
                "credentials on every runner."
            )

    def test_main_workflow_never_mentions_a_ledger_deploy_target(self) -> None:
        main_yml = (_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text()
        for target in LEDGER_TARGETS:
            assert target not in main_yml


class TestLedgerDeployTargetsExist:
    def test_all_three_targets_are_defined(self) -> None:
        tasks = _taskfile()["tasks"]
        for target in LEDGER_TARGETS:
            assert target in tasks, f"{target!r} is missing from Taskfile.yml"

    def test_image_and_deploy_require_tag(self) -> None:
        tasks = _taskfile()["tasks"]
        assert "TAG" in tasks["ledger:image"]["requires"]["vars"]
        assert "TAG" in tasks["ledger:deploy"]["requires"]["vars"]

    def test_image_builds_from_the_repo_root_context(self) -> None:
        cmds = [cmd for cmd in _taskfile()["tasks"]["ledger:image"]["cmds"] if isinstance(cmd, str)]
        assert any("packages/pulse-ledger/Dockerfile" in cmd for cmd in cmds)
        # Build context is the repo root (a bare trailing `.`), not the package directory —
        # pulse-core is a workspace sibling `Dockerfile` copies in from there.
        assert any(cmd.rstrip().endswith(" .") for cmd in cmds)
