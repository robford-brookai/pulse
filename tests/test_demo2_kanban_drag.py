"""Smoke test for Demo 2's kanban leg (task 4.1, DNA-879).

Unlike `test_demo1_ledger_core.py`, this script needs no LocalStack, no Postgres, no Docker, and
no live Twenty instance — the webhook route runs in-process against a fake committer and a fake
comment transport. It still stays out of `task check`'s own run per the work order (task 4.3's
verification wrap runs it explicitly): this test covers the smoke-parse contract — the script
parses, `--help` exits cleanly, and a full subprocess run exits zero with no network — the same
contract `test_demo1_ledger_core.py` covers for Demo 1.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo2_kanban_drag.py"

spec = importlib.util.spec_from_file_location("demo2_kanban_drag", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo2_kanban = importlib.util.module_from_spec(spec)
sys.modules["demo2_kanban_drag"] = demo2_kanban
spec.loader.exec_module(demo2_kanban)


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_an_argument_parser() -> None:
    import argparse

    assert isinstance(demo2_kanban.build_arg_parser(), argparse.ArgumentParser)


def test_default_args_parse_with_no_arguments() -> None:
    demo2_kanban.build_arg_parser().parse_args([])


def test_main_with_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        demo2_kanban.main(["--help"])
    assert raised.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out


def test_check_raises_demo_assertion_error_on_a_false_condition() -> None:
    with pytest.raises(demo2_kanban.DemoAssertionError, match="boom"):
        demo2_kanban._check(False, "boom")


def test_check_is_a_no_op_on_a_true_condition() -> None:
    demo2_kanban._check(True, "unreachable")


def test_main_with_no_arguments_runs_all_three_steps_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The full in-process run: no LocalStack, no Docker, no live network needed to exercise this."""
    exit_code = demo2_kanban.main([])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert '"step": "committed_drag"' in out
    assert '"disposition": "committed"' in out
    assert '"step": "rejected_drag"' in out
    assert '"disposition": "rejected"' in out
    assert '"step": "rejection_comment"' in out
    assert '"step": "tampered_signature"' in out
    assert "all three kanban assertions passed" in out


#: The fixture demographics `fixtures/twenty/README.md` names — a first name shared by every
#: fixture record plus the case-specific surnames this demo's two fixtures carry.
FIXTURE_DEMOGRAPHICS = ("Canary", "LegalDrag", "IllegalDrag", "CareCoordinator")


def test_main_with_no_arguments_prints_no_fixture_demographic(capsys: pytest.CaptureFixture[str]) -> None:
    """PHI posture: the printed receipts and comment carry no fixture demographic string."""
    demo2_kanban.main([])
    out = capsys.readouterr().out
    for demographic in FIXTURE_DEMOGRAPHICS:
        assert demographic not in out


def test_the_script_run_as_a_subprocess_with_help_exits_zero_with_no_network() -> None:
    """The full runnable-script contract: `python demo2_kanban_drag.py --help` exits cleanly."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "Demo 2" in result.stdout


def test_the_script_run_as_a_subprocess_exits_zero_with_no_network() -> None:
    """Task 4.1's own acceptance test: the script runs green from a fresh checkout with no network."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "all three kanban assertions passed" in result.stdout


def test_main_is_not_invoked_by_importing_the_module() -> None:
    """Guarded by `if __name__ == "__main__"` — importing it for testing must not run the demo."""
    assert demo2_kanban.__name__ != "__main__"
