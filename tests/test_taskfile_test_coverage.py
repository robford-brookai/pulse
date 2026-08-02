"""`task test` must reach every ocean service's tests (task 4.14, DNA-781).

Wave 2b converted sixteen services and wrote tests CI never ran: `TESTED_PATHS`
honestly excluded `packages/ocean/services`, so a green `task check` said nothing
about the conversions. This gate pins the fix — the `test` task runs each service
suite — so a later Taskfile edit cannot silently drop them back out of CI.

The services run one pytest process per service, not as extra TESTED_PATHS
entries: every service ships a top-level `src` package and imports itself as
`from src...`, and one interpreter cannot hold sixteen different `src` packages
in `sys.modules`. The per-service invocation is the load-bearing design, so the
gate asserts on the glob that produces it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVICES_DIR = _REPO_ROOT / "packages" / "ocean" / "services"

#: The glob `test:services` iterates. One pattern covers every current service and
#: any future one, so a new service's tests join CI by existing.
_SERVICES_GLOB = "packages/ocean/services/*/tests"


def _taskfile() -> dict:
    return yaml.safe_load((_REPO_ROOT / "Taskfile.yml").read_text())


def _cmd_text(taskfile: dict, task_name: str) -> str:
    """Flatten a task's cmds (strings and `task:` refs) into one searchable string."""
    cmds = taskfile["tasks"][task_name]["cmds"]
    parts = []
    for cmd in cmds:
        if isinstance(cmd, str):
            parts.append(cmd)
        elif isinstance(cmd, dict):
            parts.append(str(cmd.get("cmd") or cmd.get("task") or ""))
    return "\n".join(parts)


def test_service_suites_run_under_task_test():
    """`test` reaches the per-service runner, and the runner iterates the glob."""
    taskfile = _taskfile()
    assert "test:services" in _cmd_text(taskfile, "test"), (
        "`task test` no longer invokes test:services — ocean's service suites "
        "would go back to never running in CI (the DNA-781 regression)."
    )
    assert _SERVICES_GLOB in _cmd_text(taskfile, "test:services"), (
        f"test:services no longer iterates {_SERVICES_GLOB!r}; a service's tests can now exist without CI running them."
    )


def test_every_service_with_tests_is_matched_by_the_glob():
    """The glob is only a guarantee if it actually matches each suite on disk.

    A service whose tests live anywhere other than `<service>/tests` is invisible
    to the runner; this fails on the service's name so the fix is obvious.
    """
    services_with_tests = {p.parent.name for p in _SERVICES_DIR.glob("*/tests")}
    matched = {Path(p).parent.name for p in _REPO_ROOT.glob(_SERVICES_GLOB)}
    assert services_with_tests == matched


def test_services_without_tests_are_the_known_two():
    """Only mongodb-connector and warehouse-sync ship no tests (stated exclusions).

    Neither has a suite to run — that is a gap in those services, not in the
    runner (flagged in DNA-781's handoff). A third name appearing here means a new
    or converted service shipped untested; add tests, don't extend this list.
    """
    untested = {p.name for p in sorted(_SERVICES_DIR.iterdir()) if p.is_dir() and not (p / "tests").is_dir()}
    assert untested == {"mongodb-connector", "warehouse-sync"}
