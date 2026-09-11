#!/usr/bin/env python3
"""The critical Postgres invariant gate: a required-vs-optional fixture mode plus the selector
that enforces what "required" actually means.

Package suites mark their mandatory Postgres-backed invariant tests (migration, atomicity, role,
reversal, concurrency, replay — one task per package wires these) with `@pytest.mark.critical` and
call `ensure_pg_binaries(mode)` from their fixture. This module supplies both halves:

- `ensure_pg_binaries` — fails setup outright in required mode when server binaries are missing,
  instead of the local-optional behavior of skipping visibly. Binary discovery here is
  deliberately PATH/env-only (no guessed install-prefix globbing): CI pins and provisions the
  server explicitly (task 1.2), so the gate should not paper over that with host-layout guessing.
- `run_critical_suite` / `evaluate_junit` — the selector. It runs the marked suite as its own
  pytest subprocess (so a hard failure or crash there can't be swallowed by the parent run) and
  reads back JUnit evidence to enforce, in required mode, that collection is nonzero and that no
  mandatory case was skipped — both of which a bare `pytest -m critical` exit code does not by
  itself distinguish from "nothing ran" or "some cases were merely skipped".

Nothing here is wired into `task check` or CI yet — that is task 1.2. This module is deliberately
self-contained (registers its own `critical` marker per invocation) so it can be exercised and
reviewed independently of that wiring.

Usage:
    python scripts/critical_pg_gate.py --mode required tests/test_critical_postgres_gate.py
    python scripts/critical_pg_gate.py --help
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

#: Server binaries the critical suite's fixtures need on PATH (or under the override env var).
PG_BINARIES = ("initdb", "pg_ctl", "postgres")

#: Env var naming a directory containing PG_BINARIES, checked before PATH.
BINDIR_ENV_VAR = "PULSE_PG_BINDIR"

#: Env var a subprocess-run critical suite reads to pick its own mode, so its fixtures agree
#: with the selector enforcing the result.
MODE_ENV_VAR = "PULSE_CRITICAL_PG_MODE"


class Mode(str, Enum):
    """Required (CI, fails closed) versus optional (local dev, skips visibly)."""

    REQUIRED = "required"
    OPTIONAL = "optional"


def find_pg_bindir(*, env: Mapping[str, str] | None = None) -> Path | None:
    """The directory holding PG_BINARIES, or None if none is found.

    Checked in order: `PULSE_PG_BINDIR` (if set, it must hold every binary — a bad override is
    a config error, not silently skipped), then each binary's location on PATH.
    """
    env = os.environ if env is None else env
    override = env.get(BINDIR_ENV_VAR)
    if override:
        candidate = Path(override)
        if all((candidate / name).is_file() for name in PG_BINARIES):
            return candidate
        return None
    path = env.get("PATH", "")
    located = {name: shutil.which(name, path=path) for name in PG_BINARIES}
    if not all(located.values()):
        return None
    # All three must actually share a directory — binaries from mismatched installs are not
    # "found", they're a different bug.
    parents = {Path(p).resolve().parent for p in located.values() if p}
    if len(parents) != 1:
        return None
    return next(iter(parents))


def ensure_pg_binaries(mode: Mode, *, env: Mapping[str, str] | None = None) -> Path:
    """Locate the server binaries, or stop the test: fail in required mode, skip in optional.

    Call from a fixture, not a test body — `pytest.fail`/`pytest.skip` raise control-flow
    exceptions pytest expects to see at setup/call time.
    """
    bindir = find_pg_bindir(env=env)
    if bindir is not None:
        return bindir
    missing = ", ".join(PG_BINARIES)
    if mode is Mode.REQUIRED:
        pytest.fail(
            f"required Postgres mode: no server binaries found ({missing}); "
            f"set {BINDIR_ENV_VAR} to a directory containing them or provision the pinned server."
        )
    pytest.skip(
        f"optional local mode: no server binaries found ({missing}); "
        f"set {BINDIR_ENV_VAR} to run Postgres-backed critical tests locally."
    )
    raise AssertionError("unreachable")  # pytest.fail/skip always raise; pragma: no cover


@dataclass(frozen=True)
class GateResult:
    """The critical suite's outcome under one mode, and whether that outcome is acceptable."""

    mode: Mode
    ok: bool
    collected: int
    passed: int
    skipped: int
    failed: int
    errors: int
    message: str


def evaluate_junit(xml_path: Path, mode: Mode) -> GateResult:
    """Apply the required-mode rules to a critical suite's JUnit evidence.

    Required mode fails on any of: zero collection, a skipped case, or a failure/error — each
    reported by name, not folded into a bare nonzero exit code. Optional mode only fails on an
    actual failure/error; skips are reported, not penalized.
    """
    # The JUnit file is our own pytest subprocess's output, not attacker-controlled input.
    root = ET.parse(xml_path).getroot()  # noqa: S314
    collected = failed = errors = skipped = 0
    for suite in root.iter("testsuite"):
        collected += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
    skipped_cases: list[str] = []
    for case in root.iter("testcase"):
        skip_el = case.find("skipped")
        if skip_el is None:
            continue
        reason = skip_el.get("message") or ""
        name = case.get("name", "?")
        skipped_cases.append(f"{name} ({reason})" if reason else name)
    passed = collected - failed - errors - skipped

    reasons: list[str] = []
    if failed or errors:
        reasons.append(f"{failed} failed, {errors} errored")
    if mode is Mode.REQUIRED:
        if collected == 0:
            reasons.append("no critical tests were collected — the invariant coverage is missing")
        if skipped:
            reasons.append(f"{skipped} required case(s) skipped: {', '.join(skipped_cases)}")
        ok = not reasons
    else:
        ok = not (failed or errors)
        if skipped:
            reasons.append(f"optional mode: {skipped} case(s) skipped: {', '.join(skipped_cases)}")

    message = "; ".join(reasons) if reasons else f"{passed}/{collected} critical tests passed"
    return GateResult(
        mode=mode,
        ok=ok,
        collected=collected,
        passed=passed,
        skipped=skipped,
        failed=failed,
        errors=errors,
        message=message,
    )


def run_critical_suite(
    paths: Sequence[str | Path],
    mode: Mode,
    *,
    marker: str = "critical",
    env: Mapping[str, str] | None = None,
    python: str = sys.executable,
) -> GateResult:
    """Run the marked suite as its own pytest subprocess and apply the required-mode rules to it.

    A separate subprocess (rather than an in-process `pytest.main`) so a required-mode setup
    failure or an interpreter-level crash in the suite under test can never be mistaken for one
    in the process doing the enforcing. The marker is registered inline (`-o markers=...`) so
    this gate needs no `pyproject.toml` change to be exercised.
    """
    run_env = dict(os.environ if env is None else env)
    run_env[MODE_ENV_VAR] = mode.value
    with tempfile.TemporaryDirectory() as tmp_dir:
        junit_path = Path(tmp_dir) / "critical-suite.xml"
        cmd = [
            python,
            "-m",
            "pytest",
            *(str(p) for p in paths),
            "-m",
            marker,
            "--strict-markers",
            "-o",
            f"markers={marker}: mandatory Postgres-backed invariant test",
            f"--junitxml={junit_path}",
            "-q",
        ]
        completed = subprocess.run(cmd, env=run_env, capture_output=True, text=True, check=False)  # noqa: S603
        if not junit_path.exists():
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            return GateResult(
                mode=mode,
                ok=False,
                collected=0,
                passed=0,
                skipped=0,
                failed=0,
                errors=0,
                message=f"critical suite produced no evidence (exit {completed.returncode}): {detail}",
            )
        return evaluate_junit(junit_path, mode)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("paths", nargs="*", default=["tests"], help="pytest target path(s) for the critical suite")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in Mode],
        default=os.environ.get(MODE_ENV_VAR, Mode.OPTIONAL.value),
        help=f"required (fail closed) or optional (skip visibly); defaults to ${MODE_ENV_VAR} or optional",
    )
    parser.add_argument("--marker", default="critical", help="pytest marker selecting the critical suite")
    args = parser.parse_args(argv)
    result = run_critical_suite(args.paths, Mode(args.mode), marker=args.marker)
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
