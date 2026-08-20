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


class TestImageInstallsEveryWorkspaceSibling:
    """A new workspace-sibling dependency must land in the Dockerfile in the same change.

    Workspace siblings are never published to an index, so `pip install pulse-ledger` inside the
    image can only resolve them off the system path — each one needs its own COPY + install
    ahead of the pulse-ledger install. Nothing else catches this: `task check` never builds the
    image (no Docker on a runner), so the failure surfaces only at deploy time, on an operator's
    clock. It cost one twenty-projection 4.1 run: the heal-back leg added `twenty-projection`
    to `[project.dependencies]` (task 3.1) and the build died at
    `No matching distribution found for twenty-projection`.
    """

    def _sibling_names(self) -> set[str]:
        """Workspace packages `pulse-ledger` declares as dependencies, by distribution name."""
        import tomllib

        ledger = tomllib.loads((_REPO_ROOT / "packages" / "pulse-ledger" / "pyproject.toml").read_text())
        declared = {
            dep.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip()
            for dep in ledger["project"]["dependencies"]
        }
        members = {path.name for path in (_REPO_ROOT / "packages").iterdir() if (path / "pyproject.toml").is_file()}
        sibling_dists = set()
        for member in sorted(members):
            meta = tomllib.loads((_REPO_ROOT / "packages" / member / "pyproject.toml").read_text())
            name = meta["project"]["name"]
            if name in declared:
                sibling_dists.add(name)
        return sibling_dists

    def test_every_declared_sibling_is_installed_in_the_image(self) -> None:
        dockerfile = (_REPO_ROOT / "packages" / "pulse-ledger" / "Dockerfile").read_text()
        missing = sorted(
            name
            for name in self._sibling_names()
            if f"packages/{name}" not in dockerfile or f"/libs/{name}" not in dockerfile
        )
        assert not missing, (
            f"pulse-ledger declares workspace sibling(s) {missing} that its Dockerfile never "
            "installs — the image build will fail at 'No matching distribution found'. Add a "
            "COPY packages/<name> /libs/<name> plus an install step before the pulse-ledger "
            "install."
        )
