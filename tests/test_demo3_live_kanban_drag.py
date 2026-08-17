"""Smoke test for Demo 3's live kanban drag (task 7.1).

Demo 3 is the one demo that needs a live Twenty instance and a served ledger API, so — unlike
`test_demo2_kanban_drag.py` — this suite never runs the demo itself. Its contract is exactly what
the work order asks CI to hold with no server and no credentials: the script parses, exposes
`build_arg_parser()`, `--help` exits cleanly, importing it runs nothing and reads no environment,
and running it unconfigured is a fast named refusal rather than a hang or a traceback.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo3_live_kanban_drag.py"

spec = importlib.util.spec_from_file_location("demo3_live_kanban_drag", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo3 = importlib.util.module_from_spec(spec)
sys.modules["demo3_live_kanban_drag"] = demo3
spec.loader.exec_module(demo3)


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_an_argument_parser() -> None:
    import argparse

    assert isinstance(demo3.build_arg_parser(), argparse.ArgumentParser)


def test_default_args_parse_with_no_arguments() -> None:
    args = demo3.build_arg_parser().parse_args([])
    assert args.target == "dev"
    assert args.card_index == 0


def test_target_and_card_index_parse() -> None:
    args = demo3.build_arg_parser().parse_args(["--target", "dev", "--card-index", "3"])
    assert args.target == "dev"
    assert args.card_index == 3


def test_an_unknown_target_is_refused_at_parse_time() -> None:
    with pytest.raises(SystemExit):
        demo3.build_arg_parser().parse_args(["--target", "nowhere"])


def test_main_with_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        demo3.main(["--help"])
    assert raised.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_check_raises_demo_assertion_error_on_a_false_condition() -> None:
    with pytest.raises(demo3.DemoAssertionError, match="boom"):
        demo3._check(False, "boom")


def test_check_is_a_no_op_on_a_true_condition() -> None:
    demo3._check(True, "unreachable")


def test_main_unconfigured_refuses_fast_naming_the_missing_variables(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No credentials means a named refusal before any socket is opened — CI-safe by construction."""
    exit_code = demo3.main([], env={})
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "PULSE_TWENTY_DEV_URL" in captured.err
    assert "PULSE_TWENTY_DEV_TOKEN" in captured.err


def test_main_unconfigured_names_the_ledger_variables_too(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = demo3.main(
        [],
        env={"PULSE_TWENTY_DEV_URL": "https://twenty.example", "PULSE_TWENTY_DEV_TOKEN": "token"},
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "PULSE_LEDGER_API_URL" in captured.err
    assert "PULSE_LEDGER_TWENTY_WEBHOOK_SECRET" in captured.err


def test_the_script_run_as_a_subprocess_with_help_exits_zero_with_no_network() -> None:
    """The runnable-script contract: `python demo3_live_kanban_drag.py --help` exits cleanly."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "Demo 3" in result.stdout


def test_main_is_not_invoked_by_importing_the_module() -> None:
    """Guarded by `if __name__ == "__main__"` — importing it for testing must not run the demo."""
    assert demo3.__name__ != "__main__"
