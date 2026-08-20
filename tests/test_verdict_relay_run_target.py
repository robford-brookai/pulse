"""`task relay:run TARGET=<env>` exists and stays out of `check` (billing-state task 3.2,
spec verdict-relay-trigger: "The relay runs by a credentialed task target, outside check").

Two halves of one contract, and each is worthless without the other:

- The target exists, is described, and requires TARGET, so an operator (and the schedules poll's
  own runbook) has one invocation to reach the relay's production wiring.
- It is never reachable from `check` through Taskfile `task:` refs, and never named in
  `.github/workflows/main.yml`, so `check` stays offline and credential-free — the same posture
  `test_ledger_deploy_targets.py` pins for the ledger's deploy artifacts and
  `test_twenty_app_scaffold.py` pins for the credentialed Twenty targets.

The reachability half is what makes the spec scenario ("Check stays offline while the target
exists") checkable in a suite that has no credentials and no Snowflake: the closure is computed
from the committed `Taskfile.yml`, so nothing here runs the relay.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]

RELAY_TARGET = "relay:run"

#: The schedules-package poll entry task 3.1 wired (`schedules.cli verdict-relay-poll`). The task
#: target invokes that entry rather than a second production-wiring path of its own.
POLL_SUBCOMMAND = "verdict-relay-poll"


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


class TestTheTargetExists:
    def test_relay_run_is_defined_and_described(self) -> None:
        tasks = _taskfile()["tasks"]
        assert RELAY_TARGET in tasks, f"Taskfile.yml does not define {RELAY_TARGET!r}"
        assert tasks[RELAY_TARGET].get("desc"), (
            f"{RELAY_TARGET} has no desc — it would not appear in the grouped default listing"
        )

    def test_relay_run_requires_target(self) -> None:
        """Credentialed by design: no TARGET, no run — same posture as `twenty:deploy`."""
        spec = _taskfile()["tasks"][RELAY_TARGET]
        assert "TARGET" in (spec.get("requires") or {}).get("vars", []), (
            f"{RELAY_TARGET} does not require TARGET — it would run without naming the credentialed environment"
        )

    def test_relay_run_invokes_the_schedules_poll_entry(self) -> None:
        """One production-wiring path, not two: the target runs task 3.1's poll subcommand."""
        cmds = [cmd for cmd in _taskfile()["tasks"][RELAY_TARGET]["cmds"] if isinstance(cmd, str)]
        assert any(POLL_SUBCOMMAND in cmd for cmd in cmds), (
            f"{RELAY_TARGET} does not invoke `{POLL_SUBCOMMAND}` — it would need its own copy of the "
            "environment resolution `verdict_relay.production` already owns"
        )


class TestCheckStaysOffline:
    """`task check` must stay runnable with only the toolchain CI installs — no credentials."""

    def test_check_never_reaches_relay_run(self) -> None:
        assert RELAY_TARGET not in _closure(_taskfile(), "check"), (
            f"`task check` reaches {RELAY_TARGET!r} — the check contract would need Snowflake and "
            "ledger credentials on every runner"
        )

    def test_main_workflow_never_mentions_relay_run(self) -> None:
        main_yml = (_REPO_ROOT / ".github" / "workflows" / "main.yml").read_text()
        assert RELAY_TARGET not in main_yml
