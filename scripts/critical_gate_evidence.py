#!/usr/bin/env python3
"""Machine-readable evidence for the critical Postgres gate, plus its own validator (task 1.2,
`critical-path-verification`).

`scripts/critical_pg_gate.py` (task 1.1) runs the marked suite and decides pass/fail; this module
wraps that result with what the spec's "Verification evidence is machine-readable and safe"
requirement asks for beyond a boolean: the commit, the actual Python/Postgres versions the run
used, suite identifiers, and the coverage scopes the same run is expected to satisfy — written to
a JSON file that never presents a skipped or missing case as passed, and never carries a
credential or payload value.

`validate_evidence` is a second, independent check over that JSON: it re-derives the same
pass/fail judgement from the evidence's own counts rather than trusting `GateResult.ok`, so a
gate that lies about its own outcome (or evidence hand-edited/corrupted after the fact) is still
caught. `main` runs the suite, writes the evidence, validates it, and exits nonzero if either the
gate or the validator objects — used by `task test:critical` (Taskfile.yml).

Usage:
    python scripts/critical_gate_evidence.py --mode required packages/pulse-ledger/tests
    python scripts/critical_gate_evidence.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import critical_pg_gate as gate

#: Substrings that must never appear in evidence — a credential, secret, or payload value would
#: mean this file leaked something the spec says it must not.
FORBIDDEN_TERMS = ("password", "secret", "token", "credential", "authorization")

#: Every field a consumer (the validator, a human, a future dashboard) may rely on being present.
REQUIRED_FIELDS = frozenset({
    "schema_version",
    "commit",
    "mode",
    "marker",
    "suite_paths",
    "versions",
    "counts",
    "ok",
    "message",
    "coverage_scopes",
})

#: The independent coverage floors this change enforces (design.md decision 3); overridable via
#: repeated `--coverage-scope NAME:FLOOR` for testing.
DEFAULT_COVERAGE_SCOPES = (("pulse-ledger", 80), ("pulse-core", 80))


@dataclass(frozen=True)
class EvidenceValidation:
    """The validator's verdict: ok, or a list of concrete reasons it is not."""

    ok: bool
    reasons: tuple[str, ...]


def python_version() -> str:
    return platform.python_version()


def postgres_version(bindir: Path | None) -> str | None:
    """The server's own version string (e.g. "16.4"), or None if no bindir was found.

    Parsed from `postgres --version` rather than assumed from a package name — an evidence file
    that names a version should name the version that actually ran, not the one CI meant to
    install.
    """
    if bindir is None:
        return None
    completed = subprocess.run(  # noqa: S603 — fixed argv, a binary this same process located
        [str(bindir / "postgres"), "--version"], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        return None
    # "postgres (PostgreSQL) 16.4" -> "16.4"; Homebrew appends a trailing "(Homebrew)" token, so
    # take the first token that looks like a version number rather than assuming it is the last.
    for token in completed.stdout.split():
        if re.fullmatch(r"\d+(\.\d+)*", token):
            return token
    return None


def _default_commit() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    git = shutil.which("git")
    if git is None:
        return "unknown"
    completed = subprocess.run([git, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)  # noqa: S603
    return completed.stdout.strip() or "unknown"


def build_evidence(
    result: gate.GateResult,
    *,
    commit: str,
    python_version: str,
    postgres_version: str | None,
    marker: str,
    suite_paths: Sequence[str | Path],
    coverage_scopes: Sequence[tuple[str, int]],
) -> dict:
    """A JSON-serializable receipt for one critical-suite run.

    Every field is a name, a count, or a version — never a credential or payload value (the
    fields `run_critical_suite`/`evaluate_junit` compute carry none, so this is a shape guarantee,
    not a redaction step).
    """
    return {
        "schema_version": 1,
        "commit": commit,
        "mode": result.mode.value,
        "marker": marker,
        "suite_paths": [str(p) for p in suite_paths],
        "versions": {"python": python_version, "postgres": postgres_version},
        "counts": {
            "collected": result.collected,
            "passed": result.passed,
            "skipped": result.skipped,
            "failed": result.failed,
            "errors": result.errors,
        },
        "ok": result.ok,
        "message": result.message,
        "coverage_scopes": [{"name": name, "floor": floor} for name, floor in coverage_scopes],
    }


def write_evidence(evidence: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


def _walk_strings(value: object, prefix: str = "") -> list[tuple[str, str]]:
    """Every (dotted-path, string-value) leaf in a JSON-shaped structure."""
    out: list[tuple[str, str]] = []
    if isinstance(value, str):
        out.append((prefix or "<root>", value))
    elif isinstance(value, Mapping):
        for key, sub in value.items():
            out.extend(_walk_strings(sub, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            out.extend(_walk_strings(sub, f"{prefix}[{index}]"))
    return out


def _count_reasons(evidence: Mapping[str, Any]) -> list[str]:
    """Collection/skip/failure reasons derived from the evidence's own counts, per mode."""
    reasons: list[str] = []
    counts = evidence["counts"]
    mode = evidence["mode"]
    collected = counts.get("collected", 0)
    skipped = counts.get("skipped", 0)
    failed = counts.get("failed", 0)
    errors = counts.get("errors", 0)

    if collected == 0:
        reasons.append("evidence reports zero critical tests collected — no invariant coverage ran")
    if failed or errors:
        reasons.append(f"evidence reports {failed} failed / {errors} errored case(s)")
    if mode == "required":
        if skipped:
            reasons.append(f"required-mode evidence reports {skipped} skipped case(s) — a skip is not a pass")
        if not evidence.get("versions", {}).get("postgres"):
            reasons.append("required-mode evidence has no recorded Postgres version")
    return reasons


def _leaked_term_reasons(evidence: Mapping[str, Any]) -> list[str]:
    """Every string field that contains a forbidden term, wherever it is nested."""
    reasons: list[str] = []
    for path, string_value in _walk_strings(evidence):
        lowered = string_value.lower()
        for forbidden in FORBIDDEN_TERMS:
            if forbidden in lowered:
                reasons.append(f"evidence field '{path}' contains a forbidden term ({forbidden!r})")
    return reasons


def validate_evidence(evidence: Mapping[str, Any]) -> EvidenceValidation:
    """Re-derive tested-vs-skipped from the evidence's own counts; never trust `ok` alone.

    Required mode fails the same three ways the gate itself does — zero collection, any skipped
    case, a failure/error — plus a missing recorded Postgres version, which the gate does not
    check but the evidence spec requires. A forbidden term anywhere in a string value fails
    regardless of mode.
    """
    missing_fields = REQUIRED_FIELDS - evidence.keys()
    if missing_fields:
        reason = f"evidence missing required field(s): {', '.join(sorted(missing_fields))}"
        return EvidenceValidation(ok=False, reasons=(reason,))

    reasons = _count_reasons(evidence)
    if evidence.get("ok") is True and reasons:
        reasons.append("evidence claims ok=true despite the above")
    reasons.extend(_leaked_term_reasons(evidence))

    return EvidenceValidation(ok=not reasons, reasons=tuple(reasons))


def _parse_coverage_scope(raw: str) -> tuple[str, int]:
    name, _, floor = raw.partition(":")
    if not floor:
        raise argparse.ArgumentTypeError(f"--coverage-scope must be NAME:FLOOR, got {raw!r}")  # noqa: TRY003
    try:
        return name, int(floor)
    except ValueError as exc:
        msg = f"--coverage-scope floor must be an integer, got {raw!r}"
        raise argparse.ArgumentTypeError(msg) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "paths",
        nargs="*",
        default=["packages/pulse-ledger/tests", "packages/pulse-core/tests"],
        help="pytest target path(s) for the critical suite",
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in gate.Mode],
        default=os.environ.get(gate.MODE_ENV_VAR, gate.Mode.OPTIONAL.value),
        help=f"required (fail closed) or optional (skip visibly); defaults to ${gate.MODE_ENV_VAR} or optional",
    )
    parser.add_argument("--marker", default="critical", help="pytest marker selecting the critical suite")
    parser.add_argument(
        "--commit",
        default=None,
        help="commit sha recorded in evidence; defaults to $GITHUB_SHA or `git rev-parse HEAD`",
    )
    parser.add_argument("--evidence-out", type=Path, default=Path(".planning/evidence/critical-gate.json"))
    parser.add_argument("--junit-out", type=Path, default=Path(".planning/evidence/critical-suite.xml"))
    parser.add_argument(
        "--coverage-scope",
        action="append",
        type=_parse_coverage_scope,
        default=None,
        metavar="NAME:FLOOR",
        help="repeatable; overrides the default pulse-ledger:80, pulse-core:80 scopes recorded in evidence",
    )
    args = parser.parse_args(argv)

    mode = gate.Mode(args.mode)
    commit = args.commit or _default_commit()
    coverage_scopes = args.coverage_scope or list(DEFAULT_COVERAGE_SCOPES)

    result = gate.run_critical_suite(
        args.paths, mode, marker=args.marker, junit_out=args.junit_out, extra_args=["--import-mode=importlib"]
    )
    bindir = gate.find_pg_bindir()
    evidence = build_evidence(
        result,
        commit=commit,
        python_version=python_version(),
        postgres_version=postgres_version(bindir),
        marker=args.marker,
        suite_paths=args.paths,
        coverage_scopes=coverage_scopes,
    )
    # Written unconditionally — a failing run is exactly the run whose evidence must not
    # disappear; only a successful write could ever hide a failure.
    write_evidence(evidence, args.evidence_out)
    validation = validate_evidence(evidence)

    print(result.message)
    for reason in validation.reasons:
        print(f"evidence: {reason}", file=sys.stderr)

    return 0 if (result.ok and validation.ok) else 1


if __name__ == "__main__":
    sys.exit(main())
