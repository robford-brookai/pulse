"""DevEx inner tier: count open audit findings and freeze the audit protocol.

    uv run python scripts/devex/check.py            # run cat10, write JSON, print METRIC line
    uv run python scripts/devex/check.py --verify-only   # CHECKSUMS only
    uv run python scripts/devex/check.py --freeze        # regenerate CHECKSUMS (protocol PRs only)
    uv run python scripts/devex/check.py --prep-audit    # print runbook path and today's report paths

The metric is a count, never a 0-10: `devex_open_findings` is the number of `xfail` tests in
tests/scaffold/cat10_devex.py, one per unresolved finding. The 0-10 comes only from the LLM-judged
audit described in docs/process/devex-audit/README.md, whose files this script checksums so the
measurement cannot move with the thing measured.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "tests/scaffold/cat10_devex.py"
AUDIT_DIR = ROOT / "docs/process/devex-audit"
CHECKSUMS = AUDIT_DIR / "CHECKSUMS"
FROZEN = ("README.md", "rubric.md", "task-a.md", "task-b.md", "task-c.md")
OUT_DIR = ROOT / ".planning/devex"
RESULT = re.compile(r"^(PASSED|FAILED|XFAIL|XPASS|ERROR|SKIPPED) (\S+?)(?: - (.*))?$")


def digests() -> dict[str, str]:
    return {n: hashlib.sha256((AUDIT_DIR / n).read_bytes()).hexdigest() for n in FROZEN}


def freeze() -> None:
    CHECKSUMS.write_text("".join(f"{d}  {n}\n" for n, d in sorted(digests().items())))
    print(f"wrote {CHECKSUMS.relative_to(ROOT)}")


def verify() -> bool:
    if not CHECKSUMS.exists():
        print("CHECKSUMS missing; run --freeze in a protocol PR", file=sys.stderr)
        return False
    recorded = dict(reversed(line.split()) for line in CHECKSUMS.read_text().splitlines() if line.strip())
    changed = [n for n, d in digests().items() if recorded.get(n) != d]
    if changed:
        print(f"audit protocol changed without a CHECKSUMS update: {changed}", file=sys.stderr)
        return False
    return True


def run_gate() -> dict[str, list[dict]]:
    cmd = [sys.executable, "-m", "pytest", str(GATE), "-q", "-rA", "-p", "no:cacheprovider", "--no-header"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603
    results: dict[str, list[dict]] = {k: [] for k in ("PASSED", "FAILED", "XFAIL", "XPASS", "ERROR", "SKIPPED")}
    for line in r.stdout.splitlines():
        m = RESULT.match(line.strip())
        if m:
            status, node, reason = m.groups()
            results[status].append({"test": node.split("::", 1)[-1], "reason": reason or ""})
    if r.returncode not in (0, 1) or not any(results.values()):
        print(r.stdout[-3000:], r.stderr[-3000:], file=sys.stderr)
        print("cat10 did not run", file=sys.stderr)
        raise SystemExit(2)
    return results


def check() -> int:
    ok = verify()
    results = run_gate()
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    today = dt.date.today().isoformat()
    payload = {
        "date": today,
        "head": head,
        "open_findings": len(results["XFAIL"]),
        "regressions": len(results["FAILED"]) + len(results["ERROR"]),
        "fixed_but_still_marked": len(results["XPASS"]),
        "protocol_frozen": ok,
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{today}-check.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    for row in results["XFAIL"]:
        print(f"open   {row['test']}")
    for row in results["FAILED"] + results["ERROR"]:
        print(f"REGRESSION {row['test']}")
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"METRIC devex_open_findings={payload['open_findings']}")
    return 0 if ok and payload["regressions"] == 0 else 1


def prep_audit() -> None:
    today = dt.date.today().isoformat()
    print((AUDIT_DIR / "README.md").read_text())
    print("Report paths for this audit:")
    for kind in ("devex-audit-evidence", "devex-scorecard", "devex-audit-qa"):
        print(f"  .planning/reports/{today}-{kind}.md")
    prior = sorted((ROOT / ".planning/reports").glob("*-devex-scorecard.md"))
    print(f"Prior scorecard: {prior[-1].relative_to(ROOT) if prior else 'none'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verify-only", action="store_true")
    p.add_argument("--freeze", action="store_true")
    p.add_argument("--prep-audit", action="store_true")
    a = p.parse_args(argv)
    if a.freeze:
        freeze()
        return 0
    if a.verify_only:
        return 0 if verify() else 1
    if a.prep_audit:
        prep_audit()
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
