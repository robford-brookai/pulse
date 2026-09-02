"""Smoke-parse and harness-unit tests for Demo 5 (task 2.1).

`scripts/demo/demo5_end_to_end.py` needs the LocalStack + Postgres compose stack, so per the
roadmap's demo convention it stays out of `task check`'s own run. Two things do run under `check`:

- The smoke-parse contract every demo script holds (`test_demo1_ledger_core.py`'s precedent):
  the script imports cleanly with no I/O, its argument parser builds, and `--help` exits cleanly.
- A unit test of the harness loop itself (`run_walk`), against two fake `Stage` implementations —
  no compose stack, no ledger, no fixtures — asserting stop-on-first-failure and the receipt shape
  the spec pins ("a receipt naming each stage, its assertion count, and the subject keys it
  touched").
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "demo" / "demo5_end_to_end.py"

spec = importlib.util.spec_from_file_location("demo5_end_to_end", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
demo5 = importlib.util.module_from_spec(spec)
sys.modules["demo5_end_to_end"] = demo5
spec.loader.exec_module(demo5)


# --- Smoke-parse contract -------------------------------------------------------------------------


def test_the_script_exists_and_is_executable_by_python() -> None:
    assert SCRIPT_PATH.is_file()


def test_build_arg_parser_returns_an_argument_parser() -> None:
    assert isinstance(demo5.build_arg_parser(), argparse.ArgumentParser)


def test_default_args_parse_with_no_arguments() -> None:
    args = demo5.build_arg_parser().parse_args([])
    assert args.skip_compose_up is False
    assert args.live is False
    assert "ledger" in args.database_url


def test_help_exits_cleanly_with_no_network_or_stack() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, no interpolated input
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_stages_are_wired_in_spec_order() -> None:
    names = [stage.name for stage in demo5.STAGES]
    assert names == ["identity_resolution", "consent_ingress", "board_drag", "verdict_declare"]


# --- Harness unit tests: run_walk over fake stages -------------------------------------------------


class _FakeStage:
    """A minimal `Stage`: records whether `setup`/`run` were called, optionally fails."""

    def __init__(
        self, name: str, *, fail: bool = False, assertion_count: int = 1, subject_keys: tuple[str, ...] = ()
    ) -> None:
        self.name = name
        self._fail = fail
        self._assertion_count = assertion_count
        self._subject_keys = subject_keys
        self.setup_called = False
        self.run_called = False

    def setup(self, ctx: object) -> None:
        del ctx
        self.setup_called = True

    def run(self, ctx: object) -> object:
        del ctx
        self.run_called = True
        if self._fail:
            message = f"{self.name} deliberately failed"
            raise demo5.DemoAssertionError(message)
        return demo5.StageReceipt(self.name, assertion_count=self._assertion_count, subject_keys=self._subject_keys)


def test_run_walk_returns_a_receipt_per_stage_in_order() -> None:
    stages = [
        _FakeStage("first", assertion_count=2, subject_keys=("patient-1",)),
        _FakeStage("second", assertion_count=3, subject_keys=("patient-1", "episode-1")),
    ]
    receipts = demo5.run_walk(stages, ctx=object())

    assert [r.stage for r in receipts] == ["first", "second"]
    assert receipts[0].assertion_count == 2
    assert receipts[0].subject_keys == ("patient-1",)
    assert receipts[1].assertion_count == 3
    assert receipts[1].subject_keys == ("patient-1", "episode-1")
    assert all(stage.setup_called and stage.run_called for stage in stages)


def test_run_walk_stops_on_first_failure_and_never_runs_later_stages() -> None:
    first = _FakeStage("first")
    failing = _FakeStage("failing", fail=True)
    never_runs = _FakeStage("never_runs")

    with pytest.raises(demo5.StageFailure) as excinfo:
        demo5.run_walk([first, failing, never_runs], ctx=object())

    assert excinfo.value.stage_name == "failing"
    assert "deliberately failed" in excinfo.value.message
    assert first.run_called is True
    assert failing.run_called is True
    assert never_runs.setup_called is False
    assert never_runs.run_called is False


def test_stage_receipt_shape() -> None:
    receipt = demo5.StageReceipt("a_stage", assertion_count=5, subject_keys=("k1", "k2"))
    assert receipt.stage == "a_stage"
    assert receipt.assertion_count == 5
    assert receipt.subject_keys == ("k1", "k2")


def test_print_receipt_does_not_raise_on_an_empty_or_populated_list(capsys: pytest.CaptureFixture[str]) -> None:
    demo5.print_receipt([])
    demo5.print_receipt([demo5.StageReceipt("a_stage", assertion_count=1, subject_keys=("k1",))])
    captured = capsys.readouterr()
    assert "Demo 5 receipt" in captured.out
    assert "a_stage" in captured.out
