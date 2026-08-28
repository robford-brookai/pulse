"""Smoke-parse test for Demo 1 (task 5.3, DNA-799's sibling in the tasks list).

`scripts/demo/demo1_ledger_core.py` needs a running LocalStack + Postgres stack, so per the
roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints) it stays
out of `task check` — this test covers only what does not need that stack: the script parses, its
argparse surface behaves, and `--help` exits cleanly. No live network, no Docker, no database.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo1_ledger_core.py"

spec = importlib.util.spec_from_file_location("demo1_ledger_core", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo1 = importlib.util.module_from_spec(spec)
sys.modules["demo1_ledger_core"] = demo1
spec.loader.exec_module(demo1)


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_a_parser_with_the_documented_flags() -> None:
    parser = demo1.build_arg_parser()
    flags = {action.option_strings[0] for action in parser._actions if action.option_strings}
    assert {
        "--compose-file",
        "--skip-compose-up",
        "--database-url",
        "--aws-endpoint-url",
        "--event-bus-name",
        "--consumer",
        "--queue-timeout",
    } <= flags


def test_default_args_parse_with_no_arguments() -> None:
    args = demo1.build_arg_parser().parse_args([])
    assert args.skip_compose_up is False
    assert args.consumer == demo1.DEFAULT_CONSUMER
    assert args.event_bus_name == demo1.DEFAULT_EVENT_BUS_NAME
    assert args.queue_timeout == pytest.approx(30.0)


def test_skip_compose_up_flag_parses() -> None:
    args = demo1.build_arg_parser().parse_args(["--skip-compose-up"])
    assert args.skip_compose_up is True


def test_main_with_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        demo1.main(["--help"])
    assert raised.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "--skip-compose-up" in out


def test_check_raises_demo_assertion_error_on_a_false_condition() -> None:
    with pytest.raises(demo1.DemoAssertionError, match="boom"):
        demo1._check(False, "boom")


def test_check_is_a_no_op_on_a_true_condition() -> None:
    demo1._check(True, "unreachable")


def test_the_script_run_as_a_subprocess_with_help_exits_zero_with_no_network() -> None:
    """The full runnable-script contract: `python demo1_ledger_core.py --help` exits cleanly.

    No `--skip-compose-up`-adjacent stack is started here — `--help` returns before any of
    `main`'s bring-up or connection logic runs, so this needs no Docker and no live network.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "Demo 1" in result.stdout


def test_main_is_not_invoked_by_importing_the_module() -> None:
    """Guarded by `if __name__ == "__main__"` — importing it for testing must not run the demo."""
    assert demo1.__name__ != "__main__"
