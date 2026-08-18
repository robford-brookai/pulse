"""`packages/twenty-app` is a wired-in npm workspace member (pulse-app-scaffold task 1.1).

The 1.1 lesson from `pulse-ledger-core`, restated in this change's tasks.md: declared
scope must equal executed scope. A package can exist on disk while nothing reaches it —
and this one is the repo's first TypeScript package, so it has its own path list
(`workspaces` in the root `package.json`) and its own runner (`twenty:test`) rather than
riding the Python ones. This gate pins both wirings, the pinned toolchain, the layout the
generator writes into, and two properties of the surface around them:

- `uid-map.json` is a flat, sorted map of canonical UUIDs — task 2.1 landed the initial
  mint as a reviewed diff, because a generator that mints its own identifiers recreates
  fields on every sync (design.md Decision 2). Whether the map *covers* the model is
  `packages/pulse-core/tests/test_twenty_model.py`'s gate, not this one;
- `twenty:test` is reachable from `task check` *and* the job that runs `task check` sets
  node up first (task 3.4). The two halves are one fact: a `check` that shells out to
  `npm` on a runner with no node is red CI, which is exactly what `docs/ci-lessons.md`
  exists to prevent, so neither half is allowed to drift away from the other. The
  credential- and JVM-dependent targets (`twenty:deploy`, `catalog:release`,
  `synthea:regen`) stay out of `check` for the same reason inverted — the gate must be
  runnable with nothing but the toolchain CI installs.
  `twenty:validate` (task 2.3) needs no toolchain at all: it is Python-only by
  construction, reading the generated TypeScript as data rather than compiling it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from uuid import UUID

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP = _REPO_ROOT / "packages" / "twenty-app"

#: The artifact-owned half of the model, deliberately outside the app path (task 6.6): the CLI
#: derives an app's entities by globbing `**/*.ts` under the app path, and an app that declares
#: objects the workspace already owns fails to install wholesale (7.2, 45 ENTITY_ALREADY_EXISTS).
#: Objects and the three real roles are applied by `twenty:deploy` from the artifact instead, so
#: they live here, still typechecked and still covered by the app's model suite.
_MODEL = _REPO_ROOT / "packages" / "twenty-model"

#: The layout `design/platform/pulse-app-scaffold.md` promises. Every one ships a tracked
#: `.gitkeep`: git cannot track an empty directory, and a fresh clone must carry the tree
#: the generator writes into (the cat1 delivery-class rule).
_LAYOUT = (
    # The app path's own tree: the composable surface plus the placeholder default role the SDK
    # requires. `src/objects` and the real roles moved to `packages/twenty-model/` in task 6.6.
    "src/roles",
    "src/logic-functions",
    "src/views",
    "src/navigation",
    "generated",
    # The serialized Metadata API operation set task 2.2 emits and task 4.x deploys. It carries
    # tracked content rather than a `.gitkeep`: the artifact itself is committed, because the
    # deploy step reads a reviewed file and never regenerates one.
    "artifact",
    "tests",
)

#: Pinned exactly, not as ranges — a floating vitest or tsc makes the suite's result a
#: function of the day it ran.
_PINNED_DEV_DEPS = ("vitest", "typescript", "twenty-sdk")

_TWENTY_TARGETS = (
    "twenty:gen",
    "twenty:test",
    "twenty:deploy",
    "twenty:seed",
    "twenty:app:build",
    "twenty:app:publish",
)


def _is_canonical_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


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


def test_the_model_sources_live_outside_the_app_path():
    """Task 6.6: the packaged app's surface is disjoint from the artifact's, by file tree.

    The CLI globs `**/*.ts` under the app path and treats every inline `export default
    defineObject(...)` / `defineRole(...)` as an entity to publish. 7.2's live install proved an
    app cannot adopt workspace-owned entities — the full-model publish returned 45
    ENTITY_ALREADY_EXISTS and 40 FIELD_ALREADY_EXISTS — so the exclusion has to be the tree
    itself. `packages/twenty-app/tests/manifest.test.ts` asserts the resulting manifest; this is
    the same fact where a Python-only CI run can see it.
    """
    for relative in ("objects", "roles"):
        directory = _MODEL / relative
        assert directory.is_dir(), f"packages/twenty-model/{relative} missing"
        assert any(_tracked(f"packages/twenty-model/{relative}/{p.name}") for p in directory.iterdir()), (
            f"packages/twenty-model/{relative} has no tracked content — a fresh clone would not have it"
        )

    inline_entity = re.compile(r"^export default define(Object|Role)\(\{$", re.MULTILINE)
    stowaways = sorted(
        str(path.relative_to(_REPO_ROOT))
        for path in _APP.rglob("*.ts")
        if ".twenty" not in path.parts and "node_modules" not in path.parts and inline_entity.search(path.read_text())
    )
    assert stowaways == [], f"object/role sources inside the app path would publish and collide: {stowaways}"


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


def test_uid_map_is_a_flat_sorted_map_of_canonical_uuids():
    """Task 2.1 landed the reviewed mint; this gate holds the file's shape, not its contents.

    Coverage of the model + catalog surface is `packages/pulse-core/tests/test_twenty_model.py`'s
    job — it is the side that knows what keys the model needs. Here: a flat object keyed by stable
    name, sorted so a later mint reads as an append, and every value a canonical UUID string.
    """
    uid_map = json.loads((_APP / "uid-map.json").read_text())
    assert isinstance(uid_map, dict), "uid-map.json must be a flat object keyed by stable name"
    assert uid_map, "uid-map.json is empty — task 2.1 minted the initial identifiers"
    assert list(uid_map) == sorted(uid_map), "uid-map.json is unsorted; a mint should diff as an append"
    malformed = sorted(key for key, value in uid_map.items() if not _is_canonical_uuid(value))
    assert malformed == [], f"uid-map.json values are not canonical UUID strings: {malformed}"


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


def test_twenty_test_is_in_check():
    """Task 3.4: the vitest + tsc suite is a CI gate, not a target someone remembers to run."""
    assert "twenty:test" in _reachable("check"), (
        "`task check` does not reach twenty:test — the app's suite and type check would never run in CI"
    )


def test_credentialed_twenty_targets_stay_out_of_check():
    """`check` must stay runnable with only the toolchain CI installs — no secrets, no target env."""
    reached = _reachable("check")
    for target in (
        "twenty:deploy",
        "twenty:seed",
        "twenty:app:build",
        "twenty:app:publish",
        "catalog:release",
        "synthea:regen",
    ):
        assert target not in reached, (
            f"`task check` reaches {target}, which needs credentials or a JVM; CI has neither by default"
        )


def _jobs_running_check() -> list[str]:
    """Names of the main.yml jobs whose steps invoke `task check`."""
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text())
    return [
        name
        for name, job in (workflow.get("jobs") or {}).items()
        if any(re.search(r"\btask\s+check\b", str(step.get("run", ""))) for step in job.get("steps") or [])
    ]


def test_every_job_running_check_sets_node_up_first():
    """The other half of `twenty:test` in `check`: node has to be on the runner.

    Asserted per job rather than per file — a second job that grows a `task check` step
    without a node step is the same red CI, and would otherwise pass on the first job's.
    """
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text())
    jobs = _jobs_running_check()
    assert jobs, "no main.yml job runs `task check`"
    for name in jobs:
        steps = workflow["jobs"][name]["steps"]
        node_index = next(
            (i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/setup-node@")),
            None,
        )
        assert node_index is not None, (
            f"main.yml job '{name}' runs `task check`, which reaches twenty:test, but never sets node up"
        )
        check_index = next(
            i for i, step in enumerate(steps) if re.search(r"\btask\s+check\b", str(step.get("run", "")))
        )
        assert node_index < check_index, f"main.yml job '{name}' sets node up after running `task check`"


def test_the_node_version_ci_installs_satisfies_the_workspace_engine():
    """A runner on node 20 against an `engines: >=22` workspace fails inside npm, not in review."""
    required = _root_package_json()["engines"]["node"]
    match = re.search(r"(\d+)", required)
    assert match, f"root package.json engines.node is unparseable: {required!r}"
    floor = int(match.group(1))
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text())
    pinned = [
        step["with"]["node-version"]
        for job in workflow["jobs"].values()
        for step in job.get("steps") or []
        if str(step.get("uses", "")).startswith("actions/setup-node@")
    ]
    assert pinned, "no setup-node step in main.yml"
    for version in pinned:
        assert int(str(version).split(".")[0]) >= floor, (
            f"main.yml installs node {version}, below the workspace's engines requirement {required}"
        )


def test_twenty_validate_is_in_check():
    """Task 2.3: a drifted committed artifact must fail CI, which needs the gate to run there."""
    tasks = _taskfile()["tasks"]
    assert "twenty:validate" in tasks, "Taskfile.yml does not define twenty:validate"
    cmds = " ".join(str(cmd) for cmd in tasks["twenty:validate"]["cmds"])
    assert "npm" not in cmds and "npx" not in cmds, (
        f"twenty:validate reaches the node toolchain: {cmds!r} — it runs in `check`, where CI has no node"
    )
    assert "twenty:validate" in _reachable("check"), (
        "`task check` does not reach twenty:validate — the artifact gate would never run in CI"
    )
