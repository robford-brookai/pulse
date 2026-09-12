#!/usr/bin/env python3
"""The transport integration gate: a required-vs-optional fixture mode for the LocalStack relay
check, plus the selector that enforces what "required" actually means (task 2.1,
`critical-path-verification`).

`packages/pulse-ledger/tests/integration/test_localstack_relay.py` (task 4.5) already exercises
the transport end to end — commit, relay, receive — against a pinned, credential-free LocalStack
container, and already skips visibly when Docker is unavailable
(`pytest.mark.skipif(not _docker_available(), ...)`). This module is the selector layer on top of
that suite, exactly as `scripts/critical_pg_gate.py` is the selector on top of the Postgres
invariant suite: it runs the marked (`integration`) suite as its own bounded pytest subprocess —
so a hang in a container that never becomes healthy cannot hang the gate itself — and reads back
JUnit evidence to enforce, in required mode, that collection is nonzero and that no case was
skipped. A skipped case is exactly what "Docker unavailable" produces, so required mode turns
that visible-skip-in-optional-mode behavior into a fail-closed one, the same way a missing
Postgres binary fails closed in `critical_pg_gate.py` — this is what makes an unhealthy or absent
integration environment a *startup failure* of the gate rather than a silent green.

Evidence is a JSON file recording the commit, mode, marker, suite paths, and pass/fail/skip
counts — never a credential or payload value — so a required run's assurance is machine-readable,
not merely "the job was green" (the same posture task 1.2 established for the Postgres gate).

Usage:
    python scripts/transport_gate.py --mode required packages/pulse-ledger/tests/integration
    python scripts/transport_gate.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

#: Env var a subprocess-run transport suite could read to pick its own mode; kept parallel to
#: `critical_pg_gate.MODE_ENV_VAR` even though the current suite has no mode-aware fixture of its
#: own — only the selector's required-mode enforcement needs it today.
MODE_ENV_VAR = "PULSE_TRANSPORT_MODE"

#: Upper bound on one gate run (task 2.1: "bounded"). A LocalStack container that never reports
#: healthy must fail the gate, not hang the job indefinitely.
DEFAULT_TIMEOUT_SECONDS = 300.0

#: Substrings that must never appear in evidence, matching `critical_gate_evidence.FORBIDDEN_TERMS`.
FORBIDDEN_TERMS = ("password", "secret", "token", "credential", "authorization")

#: Every field a consumer of the evidence file may rely on being present.
REQUIRED_FIELDS = frozenset({
    "schema_version",
    "commit",
    "mode",
    "marker",
    "suite_paths",
    "python_version",
    "counts",
    "ok",
    "message",
    "cases",
})


class Mode(str, Enum):
    """Required (CI, fails closed) versus optional (local dev, skips visibly)."""

    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class TestCaseOutcome:
    """One test case's name, outcome, and (for a failure/error/skip) its message — the detail a
    bare pass/fail count cannot carry, and what task 2.1's coordinator review found missing from
    the evidence: the receipt named neither the failing test nor the reason."""

    name: str
    outcome: str  # "passed" | "failed" | "error" | "skipped"
    detail: str = ""


@dataclass(frozen=True)
class GateResult:
    """The transport suite's outcome under one mode, and whether that outcome is acceptable."""

    mode: Mode
    ok: bool
    collected: int
    passed: int
    skipped: int
    failed: int
    errors: int
    message: str
    #: Every non-passing case, name and reason — never just a count. Populated by
    #: `evaluate_junit`; empty for the timeout/no-evidence paths, which have no JUnit to read.
    cases: tuple[TestCaseOutcome, ...] = ()
    #: The subprocess's own stdout/stderr, so a CI job log shows pytest's failure output rather
    #: than only this gate's one-line summary. Empty unless a suite actually ran.
    stdout: str = ""
    stderr: str = ""


def _case_outcome(case: ET.Element) -> TestCaseOutcome:
    """One `<testcase>` element's outcome and, for anything but a clean pass, its own message —
    what makes the gate's evidence and CI-log message name the actual test and reason, not just a
    count."""
    name = case.get("name", "?")
    for tag, outcome in (("skipped", "skipped"), ("failure", "failed"), ("error", "error")):
        el = case.find(tag)
        if el is not None:
            detail = (el.get("message") or el.text or "").strip()
            return TestCaseOutcome(name=name, outcome=outcome, detail=detail)
    return TestCaseOutcome(name=name, outcome="passed")


def evaluate_junit(xml_path: Path, mode: Mode) -> GateResult:
    """Apply the required-mode rules to a transport suite's JUnit evidence.

    Required mode fails on any of: zero collection, a skipped case (Docker/LocalStack
    unavailable, or the suite's own health-check loop giving up), or a failure/error (a dropped
    delivery, a broken duplicate/redrive assumption, or any other assertion the suite makes).
    Optional mode only fails on an actual failure/error; skips are reported, not penalized.
    """
    # The JUnit file is our own pytest subprocess's output, not attacker-controlled input.
    root = ET.parse(xml_path).getroot()  # noqa: S314
    collected = failed = errors = skipped = 0
    for suite in root.iter("testsuite"):
        collected += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))

    cases = tuple(_case_outcome(case) for case in root.iter("testcase"))
    passed = collected - failed - errors - skipped

    def _named(outcome: str) -> list[str]:
        return [f"{c.name}: {c.detail}" if c.detail else c.name for c in cases if c.outcome == outcome]

    reasons: list[str] = []
    if failed or errors:
        detail = "; ".join(_named("failed") + _named("error"))
        reasons.append(f"{failed} failed, {errors} errored — {detail}")
    if mode is Mode.REQUIRED:
        if collected == 0:
            reasons.append("no transport tests were collected — the integration check is missing")
        if skipped:
            reasons.append(f"{skipped} required case(s) skipped: {', '.join(_named('skipped'))}")
        ok = not reasons
    else:
        ok = not (failed or errors)
        if skipped:
            reasons.append(f"optional mode: {skipped} case(s) skipped: {', '.join(_named('skipped'))}")

    message = "; ".join(reasons) if reasons else f"{passed}/{collected} transport tests passed"
    return GateResult(
        mode=mode,
        ok=ok,
        collected=collected,
        passed=passed,
        skipped=skipped,
        failed=failed,
        errors=errors,
        message=message,
        cases=cases,
    )


#: A pytest plugin registering `marker` via `addinivalue_line`, written to a temp dir and loaded
#: with `-p`. Additive rather than `-o markers=...` for the same reason `critical_pg_gate.py`
#: does this: replacing the whole ini option would silently un-register every other marker a real
#: target directory's own pyproject.toml declares.
_MARKER_PLUGIN_TEMPLATE = """
def pytest_configure(config):
    config.addinivalue_line("markers", {marker!r} + ": transport integration test")
"""


def run_transport_suite(
    paths: Sequence[str | Path],
    mode: Mode,
    *,
    marker: str = "integration",
    env: Mapping[str, str] | None = None,
    python: str = sys.executable,
    junit_out: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    extra_args: Sequence[str] = (),
) -> GateResult:
    """Run the marked suite as its own bounded pytest subprocess and apply required-mode rules.

    A separate subprocess (rather than an in-process `pytest.main`) so a hard failure or crash
    there can't be swallowed by the parent run, and a `timeout_seconds` bound so a container that
    never becomes healthy fails the gate instead of hanging the job — the "or times out" half of
    the spec's transport scenario. `junit_out`, if given, is a durable copy of the JUnit evidence;
    the file under `tmp_dir` is deleted with it once this function returns.
    """
    run_env = dict(os.environ if env is None else env)
    run_env[MODE_ENV_VAR] = mode.value
    with tempfile.TemporaryDirectory() as tmp_dir:
        junit_path = Path(tmp_dir) / "transport-suite.xml"
        plugin_name = "_transport_marker_plugin"
        (Path(tmp_dir) / f"{plugin_name}.py").write_text(_MARKER_PLUGIN_TEMPLATE.format(marker=marker))
        run_env["PYTHONPATH"] = os.pathsep.join(p for p in (tmp_dir, run_env.get("PYTHONPATH")) if p)
        cmd = [
            python,
            "-m",
            "pytest",
            *(str(p) for p in paths),
            "-m",
            marker,
            "--strict-markers",
            "-p",
            plugin_name,
            f"--junitxml={junit_path}",
            "-q",
            *extra_args,
        ]
        try:
            completed = subprocess.run(  # noqa: S603
                cmd, env=run_env, capture_output=True, text=True, check=False, timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired:
            return GateResult(
                mode=mode,
                ok=False,
                collected=0,
                passed=0,
                skipped=0,
                failed=0,
                errors=0,
                message=f"transport suite timed out after {timeout_seconds:.0f}s (bounded run)",
            )
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
                message=f"transport suite produced no evidence (exit {completed.returncode}): {detail}",
            )
        if junit_out is not None:
            junit_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(junit_path, junit_out)
        result = evaluate_junit(junit_path, mode)
        return replace(result, stdout=completed.stdout, stderr=completed.stderr)


def _default_commit() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    git = shutil.which("git")
    if git is None:
        return "unknown"
    completed = subprocess.run([git, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)  # noqa: S603
    return completed.stdout.strip() or "unknown"


def write_evidence(result: GateResult, suite_paths: Sequence[str | Path], out_path: Path) -> dict[str, object]:
    """Write the gate's machine-readable receipt and return the document written.

    Never a credential, secret, or payload value — the same posture
    `critical_gate_evidence.write_evidence` holds for the Postgres gate.
    """
    document = {
        "schema_version": 1,
        "commit": _default_commit(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "mode": result.mode.value,
        "marker": "integration",
        "suite_paths": [str(p) for p in suite_paths],
        "python_version": platform.python_version(),
        "counts": {
            "collected": result.collected,
            "passed": result.passed,
            "skipped": result.skipped,
            "failed": result.failed,
            "errors": result.errors,
        },
        "ok": result.ok,
        "message": result.message,
        "cases": [
            {"name": c.name, "outcome": c.outcome, "detail": c.detail} for c in result.cases if c.outcome != "passed"
        ],
    }
    serialized = json.dumps(document, indent=2, sort_keys=True)
    lowered = serialized.lower()
    for term in FORBIDDEN_TERMS:
        if term in lowered:
            raise RuntimeError(f"evidence would leak a forbidden term: {term!r}")  # noqa: TRY003
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(serialized + "\n")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "paths",
        nargs="*",
        default=["packages/pulse-ledger/tests/integration"],
        help="pytest target path(s) for the transport suite",
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in Mode],
        default=os.environ.get(MODE_ENV_VAR, Mode.OPTIONAL.value),
        help=f"required (fail closed) or optional (skip visibly); defaults to ${MODE_ENV_VAR} or optional",
    )
    parser.add_argument("--marker", default="integration", help="pytest marker selecting the transport suite")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="bound, in seconds, on the whole suite run"
    )
    parser.add_argument(
        "--evidence-out",
        type=Path,
        default=Path(".planning/evidence/transport-gate.json"),
        help="where to write the JSON evidence receipt",
    )
    args = parser.parse_args(argv)
    result = run_transport_suite(args.paths, Mode(args.mode), marker=args.marker, timeout_seconds=args.timeout)
    write_evidence(result, args.paths, args.evidence_out)
    if not result.ok:
        # pytest's own failure output (assertion detail, traceback) — the CI job log must show
        # more than this gate's one-line summary when something actually broke.
        if result.stdout.strip():
            print(result.stdout)
        if result.stderr.strip():
            print(result.stderr, file=sys.stderr)
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
