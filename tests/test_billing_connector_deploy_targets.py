"""The billing connector's deploy artifacts are never a check step (task 3.1).

Modeled on `test_ledger_deploy_targets.py`, which computes the same reachable-from-check set for
`ledger:image`/`ledger:deploy`: `billing-connector:image` and `billing-connector:deploy` both need
something `check` must never depend on (a Docker daemon or registry/cluster credentials), so
neither may be reachable from `check` through Taskfile `task:` refs.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]

BILLING_CONNECTOR_TARGETS = ("billing-connector:image", "billing-connector:deploy")


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
    """`task check` must never reach a target needing Docker or cluster credentials."""

    def test_check_closure_excludes_every_billing_connector_deploy_target(self) -> None:
        closure = _closure(_taskfile(), "check")
        for target in BILLING_CONNECTOR_TARGETS:
            assert target not in closure, (
                f"`task check` reaches {target!r} — the check contract would need Docker/cluster "
                "credentials on every runner."
            )

    def test_main_workflow_never_mentions_a_billing_connector_deploy_target(self) -> None:
        main_yml = (_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text()
        for target in BILLING_CONNECTOR_TARGETS:
            assert target not in main_yml


class TestBillingConnectorDeployTargetsExist:
    def test_both_targets_are_defined(self) -> None:
        tasks = _taskfile()["tasks"]
        for target in BILLING_CONNECTOR_TARGETS:
            assert target in tasks, f"{target!r} is missing from Taskfile.yml"

    def test_image_and_deploy_require_tag(self) -> None:
        tasks = _taskfile()["tasks"]
        assert "TAG" in tasks["billing-connector:image"]["requires"]["vars"]
        assert "TAG" in tasks["billing-connector:deploy"]["requires"]["vars"]

    def test_deploy_also_requires_target(self) -> None:
        tasks = _taskfile()["tasks"]
        assert "TARGET" in tasks["billing-connector:deploy"]["requires"]["vars"]

    def test_image_builds_from_the_repo_root_context(self) -> None:
        cmds = [cmd for cmd in _taskfile()["tasks"]["billing-connector:image"]["cmds"] if isinstance(cmd, str)]
        assert any("packages/billing-connector/Dockerfile" in cmd for cmd in cmds)
        # Build context is the repo root (a bare trailing `.`), not the package directory —
        # pulse-core and billing are workspace siblings pulled in from there.
        assert any(cmd.rstrip().endswith(" .") for cmd in cmds)


class TestImageInstallsEveryWorkspaceSibling:
    """A new workspace-sibling dependency must land in the Dockerfile in the same change.

    Workspace siblings are never published to an index, so `pip install billing-connector` inside
    the image can only resolve them off the system path — each one needs its own COPY + install
    ahead of the billing-connector install. Nothing else catches this: `task check` never builds
    the image (no Docker on a runner), so the failure surfaces only at deploy time, on an
    operator's clock (the exact `test_ledger_deploy_targets.py` precedent this follows).
    """

    def _workspace_dists(self) -> dict[str, Path]:
        import tomllib

        root = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
        dists: dict[str, Path] = {}
        for member in root["tool"]["uv"]["workspace"]["members"]:
            manifest = _REPO_ROOT / member / "pyproject.toml"
            if manifest.is_file():
                dists[tomllib.loads(manifest.read_text())["project"]["name"]] = _REPO_ROOT / member
        return dists

    def _sibling_names(self) -> set[str]:
        """Workspace siblings `billing-connector` needs at runtime, by distribution name.

        Two sources: `[project.dependencies]` plus every `[project.optional-dependencies]` extra,
        and a source-tree scan for `import x`/`from x` naming a workspace member — a lazy import
        is still a runtime dependency (pulse-ledger's relay/ocean-broker precedent).
        """
        import tomllib

        workspace = self._workspace_dists()
        manifest = tomllib.loads((_REPO_ROOT / "packages" / "billing-connector" / "pyproject.toml").read_text())

        requirements = list(manifest["project"]["dependencies"])
        for extra in (manifest["project"].get("optional-dependencies") or {}).values():
            requirements.extend(extra)
        declared = {req.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip() for req in requirements}
        needed = {name for name in workspace if name in declared}

        by_module = {name.replace("-", "_"): name for name in workspace}
        import_pattern = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE)
        for module_file in (_REPO_ROOT / "packages" / "billing-connector" / "src").rglob("*.py"):
            for module in import_pattern.findall(module_file.read_text()):
                if module in by_module:
                    needed.add(by_module[module])

        needed.discard(manifest["project"]["name"])
        return needed

    def test_every_runtime_sibling_is_installed_in_the_image(self) -> None:
        lines = [
            line.strip()
            for line in (_REPO_ROOT / "packages" / "billing-connector" / "Dockerfile").read_text().splitlines()
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
            f"billing-connector needs workspace sibling(s) {missing} at runtime that its "
            "Dockerfile never installs. A declared one fails the image build at 'No matching "
            "distribution found'; a lazily-imported one builds fine and then dies on "
            "ModuleNotFoundError in the running container. Add a COPY <member-path> /libs/<name> "
            "plus an install step before the billing-connector install."
        )
