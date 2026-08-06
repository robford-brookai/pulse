"""Smoke test for Demo 2 (partial)'s identity slice (DNA-849, s14-identity).

Unlike `test_demo1_ledger_core.py`, this script needs no LocalStack, no Postgres, no Docker —
`identity.matcher.resolve` is a pure function — so this test runs the real script end to end, not
just its argparse surface, and stays in the default `task check` run.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo2_identity_matcher.py"

spec = importlib.util.spec_from_file_location("demo2_identity_matcher", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo2 = importlib.util.module_from_spec(spec)
sys.modules["demo2_identity_matcher"] = demo2
spec.loader.exec_module(demo2)


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_main_with_no_arguments_exits_zero_and_prints_all_four_rule_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = demo2.main([])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert '"rule_id": "identifier_exact"' in out
    assert '"rule_id": "composite_none"' in out
    assert '"rule_id": "composite_ambiguous"' in out
    assert '"rule_id": "identifier_conflict"' in out
    assert "all four identity assertions passed" in out


def test_main_with_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        demo2.main(["--help"])
    assert raised.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_the_script_run_as_a_subprocess_exits_zero_with_no_network() -> None:
    """The full runnable-script contract, driven the same way the runbook documents it."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "Demo 2 (partial): all four identity assertions passed" in result.stdout


def test_main_is_not_invoked_by_importing_the_module() -> None:
    """Guarded by `if __name__ == "__main__"` — importing it for testing must not run the demo."""
    assert demo2.__name__ != "__main__"
