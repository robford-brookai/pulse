"""The ledger's deploy artifacts are never a check step (task 4.5's serving-layer wiring).

Modeled on `test_catalog_release_deploy.py`, which computes the same reachable-from-check set for
`catalog:release`: `ledger:image`, `ledger:migrate`, and `ledger:deploy` all need something `check`
must never depend on (a Docker daemon, a real Postgres, or registry/cluster credentials), so none
of them may be reachable from `check` through Taskfile `task:` refs.
"""

from __future__ import annotations

import re
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

    def _workspace_dists(self) -> dict[str, Path]:
        """Every uv workspace member's distribution name mapped to its directory.

        Members live at two depths (`packages/x` and `packages/ocean/libs/x`), so this reads the
        workspace member list rather than globbing one level down.
        """
        import tomllib

        root = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
        dists: dict[str, Path] = {}
        for member in root["tool"]["uv"]["workspace"]["members"]:
            manifest = _REPO_ROOT / member / "pyproject.toml"
            if manifest.is_file():
                dists[tomllib.loads(manifest.read_text())["project"]["name"]] = _REPO_ROOT / member
        return dists

    def _sibling_names(self) -> set[str]:
        """Workspace siblings `pulse-ledger` needs at runtime, by distribution name.

        Two sources, because the manifest alone is not enough. `[project.dependencies]` plus every
        `[project.optional-dependencies]` extra cover what the manifest admits to. But the failure
        that motivated widening this test was a **lazy import**: `pulse_ledger.relay` imports
        `ocean_broker` inside `default_publisher()`, nothing in the manifest mentioned it, the
        image never installed it, and the relay container died on `ModuleNotFoundError: No module
        named 'ocean_broker'` the first time it tried to publish on dev (2026-08-21). So the source
        tree is scanned too: any `import x` naming a workspace member counts, declared or not.
        """
        import tomllib

        workspace = self._workspace_dists()
        ledger = tomllib.loads((_REPO_ROOT / "packages" / "pulse-ledger" / "pyproject.toml").read_text())

        requirements = list(ledger["project"]["dependencies"])
        for extra in (ledger["project"].get("optional-dependencies") or {}).values():
            requirements.extend(extra)
        declared = {req.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip() for req in requirements}
        needed = {name for name in workspace if name in declared}

        # Module name to distribution name: the workspace uses the underscore/hyphen convention
        # throughout (ocean_broker -> ocean-broker, pulse_core -> pulse-core).
        by_module = {name.replace("-", "_"): name for name in workspace}
        import_pattern = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE)
        for module_file in (_REPO_ROOT / "packages" / "pulse-ledger" / "src").rglob("*.py"):
            for module in import_pattern.findall(module_file.read_text()):
                if module in by_module:
                    needed.add(by_module[module])

        needed.discard(ledger["project"]["name"])
        return needed

    def test_every_runtime_sibling_is_installed_in_the_image(self) -> None:
        # Non-comment lines only, and an actual install instruction — not any occurrence of the
        # path. A substring check over the whole file passes on a *comment* mentioning the path,
        # which is how the first version of this test falsely passed while the install was gone.
        lines = [
            line.strip()
            for line in (_REPO_ROOT / "packages" / "pulse-ledger" / "Dockerfile").read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        installs = [line for line in lines if "install" in line]
        copies = [line for line in lines if line.upper().startswith("COPY")]
        missing = sorted(
            name
            for name in self._sibling_names()
            if not (
                any(f"/libs/{name}" in line for line in installs)
                and any(line.rstrip().endswith(f"/libs/{name}") for line in copies)
            )
        )
        assert not missing, (
            f"pulse-ledger needs workspace sibling(s) {missing} at runtime that its Dockerfile "
            "never installs. A declared one fails the image build at 'No matching distribution "
            "found'; a lazily-imported one builds fine and then dies on ModuleNotFoundError in "
            "the running container. Add a COPY <member-path> /libs/<name> plus an install step "
            "before the pulse-ledger install."
        )
