"""The demo Taskfile area (design decision 7, pulse-demo-closeout): `demo:1` … `demo:4` are
defined and none is reachable from `check`.

Same reachability-walk pattern `test_twenty_app_scaffold.py`'s
`test_credentialed_twenty_targets_stay_out_of_check` uses: `check` must stay runnable with only
the toolchain CI installs, and every demo needs either Docker/LocalStack or live dev credentials
neither CI has by default (design.md decision 7, roadmap #Demo breakpoints).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]

_DEMO_TARGETS = ("demo:1", "demo:2", "demo:3", "demo:4")


def _taskfile() -> dict:
    return yaml.safe_load((ROOT / "Taskfile.yml").read_text())


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


def test_demo_targets_are_defined() -> None:
    tasks = _taskfile()["tasks"]
    for target in _DEMO_TARGETS:
        assert target in tasks, f"Taskfile.yml does not define {target}"
        assert tasks[target].get("desc"), f"{target} has no desc — it would not appear in the grouped listing"


def test_demo_targets_stay_out_of_check() -> None:
    reached = _reachable("check")
    for target in _DEMO_TARGETS:
        assert target not in reached, (
            f"`task check` reaches {target}; every demo needs Docker/LocalStack or live dev "
            "credentials, neither of which CI has by default"
        )


def test_demo_targets_stay_out_of_verify() -> None:
    """`task verify` layers drift + spec validation onto `check` — same posture, same guard."""
    reached = _reachable("verify")
    for target in _DEMO_TARGETS:
        assert target not in reached, f"`task verify` reaches {target}"
