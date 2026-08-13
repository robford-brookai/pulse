"""`packages/twenty-app` is a wired-in npm workspace member (pulse-app-scaffold task 1.1).

The 1.1 lesson from `pulse-ledger-core`, restated in this change's tasks.md: declared
scope must equal executed scope. A package can exist on disk while nothing reaches it —
and this one is the repo's first TypeScript package, so it has its own path list
(`workspaces` in the root `package.json`) and its own runner (`twenty:test`) rather than
riding the Python ones. This gate pins both wirings, the pinned toolchain, the layout the
generator writes into, and the two things that must *not* be true yet:

- `uid-map.json` stays empty until task 2.1 mints into it as a reviewed diff, because a
  generator that mints its own identifiers recreates fields on every sync (design.md
  Decision 2);
- none of the `twenty:*` targets is reachable from `task check`. Wiring them into the
  gate is task 3.4's reviewed step, and it needs the `setup-node` step in `main.yml` to
  land in the same commit — a `check` that shells out to `npm` on a runner with no node
  is red CI, which is exactly what `docs/ci-lessons.md` exists to prevent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP = _REPO_ROOT / "packages" / "twenty-app"

#: The layout `design/platform/pulse-app-scaffold.md` promises. Every one ships a tracked
#: `.gitkeep`: git cannot track an empty directory, and a fresh clone must carry the tree
#: the generator writes into (the cat1 delivery-class rule).
_LAYOUT = (
    "src/objects",
    "src/roles",
    "src/logic-functions",
    "src/views",
    "generated",
    "tests",
)

#: Pinned exactly, not as ranges — a floating vitest or tsc makes the suite's result a
#: function of the day it ran.
_PINNED_DEV_DEPS = ("vitest", "typescript")

_TWENTY_TARGETS = ("twenty:gen", "twenty:test", "twenty:deploy")


def _taskfile() -> dict:
    return yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())


def _root_package_json() -> dict:
    return json.loads((_REPO_ROOT / "package.json").read_text())


def _app_package_json() -> dict:
    return json.loads((_APP / "package.json").read_text())


def _tracked(path: str) -> bool:
    """True when git has the path in the index — a fresh clone receives it."""
    result = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--error-unmatch", path],  # noqa: S607
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _reachable(task_name: str) -> set[str]:
    """Every target reached from ``task_name`` through deps and `task:` cmds."""
    tasks = _taskfile()["tasks"]

    def walk(name: str, seen: set[str]) -> set[str]:
        if name in seen:
            return seen
        seen.add(name)
        spec = tasks.get(name) or {}
        for dep in spec.get("deps") or []:
            walk(dep if isinstance(dep, str) else dep.get("task", ""), seen)
        for cmd in spec.get("cmds") or []:
            if isinstance(cmd, dict) and "task" in cmd:
                walk(cmd["task"], seen)
        return seen

    return walk(task_name, set())


def test_app_is_an_npm_workspace_member():
    """The root manifest is what makes `npm ci` install the package's dev deps."""
    root = _root_package_json()
    assert root.get("private") is True, "the root package.json must be private — this workspace is never published"
    assert "packages/twenty-app" in root.get("workspaces", []), (
        "packages/twenty-app is not an npm workspace member; `npm ci` would not install its dev dependencies"
    )


def test_layout_exists_and_reaches_a_fresh_clone():
    for relative in _LAYOUT:
        directory = _APP / relative
        assert directory.is_dir(), f"packages/twenty-app/{relative} missing"
        keep = f"packages/twenty-app/{relative}/.gitkeep"
        assert _tracked(keep) or any(
            _tracked(f"packages/twenty-app/{relative}/{p.name}") for p in directory.iterdir()
        ), f"{relative} has no tracked content — a fresh clone would not have the directory"


def test_dev_toolchain_is_pinned_exactly():
    dev_deps = _app_package_json().get("devDependencies", {})
    for name in _PINNED_DEV_DEPS:
        assert name in dev_deps, f"packages/twenty-app devDependencies lacks {name}"
        spec = dev_deps[name]
        assert spec[0].isdigit(), f"{name} is pinned as {spec!r}; an exact version is required, not a range"


def test_lockfile_is_committed():
    """Without a committed lock, `npm ci` has nothing to reproduce."""
    assert _tracked("package-lock.json"), "package-lock.json is not tracked — `npm ci` cannot run reproducibly"


def test_node_modules_is_ignored():
    assert "node_modules/" in (_REPO_ROOT / ".gitignore").read_text().splitlines()


def test_uid_map_is_empty_but_valid():
    """Empty-but-valid: a flat object, ready for task 2.1's reviewed mint."""
    uid_map = json.loads((_APP / "uid-map.json").read_text())
    assert isinstance(uid_map, dict), "uid-map.json must be a flat object keyed by stable name"
    assert uid_map == {}, (
        "uid-map.json carries entries; minting is task 2.1's reviewed diff, never a side effect of the scaffold"
    )


def test_a_vitest_spec_exists_for_the_runner_to_collect():
    specs = sorted(_APP.glob("tests/*.test.ts"))
    assert specs, (
        "packages/twenty-app/tests has no *.test.ts — `task twenty:test` would collect nothing and pass vacuously"
    )


def test_twenty_targets_are_defined():
    tasks = _taskfile()["tasks"]
    for target in _TWENTY_TARGETS:
        assert target in tasks, f"Taskfile.yml does not define {target}"
        assert tasks[target].get("desc"), f"{target} has no desc — it would not appear in the grouped listing"


def test_twenty_test_runs_the_vitest_suite():
    cmds = " ".join(str(cmd) for cmd in _taskfile()["tasks"]["twenty:test"]["cmds"])
    assert "vitest" in cmds or "npm" in cmds, f"twenty:test does not invoke the node toolchain: {cmds!r}"


def test_twenty_targets_are_not_yet_in_check():
    """Task 3.4 wires these into `check` together with `main.yml`'s setup-node step."""
    reached = _reachable("check")
    assert not reached & set(_TWENTY_TARGETS), (
        f"`task check` already reaches {sorted(reached & set(_TWENTY_TARGETS))}; CI has no node "
        "step yet, so this is red CI. Wiring it in is task 3.4."
    )
