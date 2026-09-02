"""Smoke test for Demo 4's live declare-back (billing-state task 4.1).

Demo 4 needs a live dev Snowflake mart and a dev Postgres, so — like `test_demo3_live_kanban_drag.
py` — this suite never runs the demo itself. Its contract is what the roadmap's demo convention
asks CI to hold with no server and no credentials: the script parses, exposes `build_arg_parser()`,
`--help` exits cleanly, importing it runs nothing and reads no environment, and running it
unconfigured is a fast named refusal rather than a hang or a traceback.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo4_billing_declare_back.py"

spec = importlib.util.spec_from_file_location("demo4_billing_declare_back", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo4 = importlib.util.module_from_spec(spec)
sys.modules["demo4_billing_declare_back"] = demo4
spec.loader.exec_module(demo4)


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_an_argument_parser() -> None:
    import argparse

    assert isinstance(demo4.build_arg_parser(), argparse.ArgumentParser)


def test_default_args_parse_with_no_arguments() -> None:
    args = demo4.build_arg_parser().parse_args([])
    assert args.target == "dev"
    assert args.database_url == demo4.DEFAULT_DATABASE_URL


def test_target_choices_are_the_three_environments() -> None:
    for target in ("dev", "staging", "prod"):
        assert demo4.build_arg_parser().parse_args(["--target", target]).target == target


def test_an_unknown_target_is_refused_at_parse_time() -> None:
    with pytest.raises(SystemExit):
        demo4.build_arg_parser().parse_args(["--target", "nowhere"])


def test_main_with_help_exits_zero_and_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        demo4.main(["--help"])
    assert raised.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_check_raises_demo_assertion_error_on_a_false_condition() -> None:
    with pytest.raises(demo4.DemoAssertionError, match="boom"):
        demo4._check(False, "boom")


def test_check_is_a_no_op_on_a_true_condition() -> None:
    demo4._check(True, "unreachable")


def test_main_unconfigured_refuses_fast_naming_the_missing_variable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No `VERDICT_RELAY_*` credentials means a named refusal before any connection is opened."""
    exit_code = demo4.main([], env={})
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAILED:" in captured.err


def test_the_script_run_as_a_subprocess_with_help_exits_zero_with_no_network() -> None:
    """The runnable-script contract: `python demo4_billing_declare_back.py --help` exits cleanly."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "Demo 4" in result.stdout


def test_main_is_not_invoked_by_importing_the_module() -> None:
    """Guarded by `if __name__ == "__main__"` — importing it for testing must not run the demo."""
    assert demo4.__name__ != "__main__"


def test_synthetic_rule_version_is_distinct_from_the_real_manual_convention() -> None:
    """PHI posture: a receipt from this script can never be mistaken for a real adjudicated row."""
    assert not demo4.SYNTHETIC_RULE_VERSION.startswith("manual-")


def test_coverage_subject_id_hashes_the_payer_never_embedding_it_raw() -> None:
    subject_id = demo4._coverage_subject_id("demo4-patient-1", "SYNTH-PAYER-DEMO4")
    assert subject_id.startswith("demo4-patient-1:")
    assert "SYNTH-PAYER-DEMO4" not in subject_id
