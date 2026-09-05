"""Time one `task check` gate and append its result to the DevEx ledger.

    uv run python scripts/devex/timing.py <target> -- <command...>

Runs <command...> under a stopwatch, appends one `{date, kind: timing, target, seconds, rc}` row
to `.planning/devex/loop.jsonl`, and exits with the command's own return code — a timed gate fails
`task check` exactly the way the untimed call would. `scripts/devex/check.py` is what reads these
rows back; keep the row shape in sync with `read_timings()` there.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / ".planning/devex/loop.jsonl"


def run(target: str, command: list[str]) -> int:
    t0 = time.monotonic()
    rc = subprocess.run(command, cwd=ROOT, check=False).returncode  # noqa: S603
    seconds = round(time.monotonic() - t0, 3)
    row = {
        "date": dt.date.today().isoformat(),
        "kind": "timing",
        "target": target,
        "seconds": seconds,
        "rc": rc,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return rc


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--" not in args:
        print("usage: timing.py <target> -- <command...>", file=sys.stderr)
        return 2
    sep = args.index("--")
    target, command = args[0], args[sep + 1 :]
    if not target or not command:
        print("usage: timing.py <target> -- <command...>", file=sys.stderr)
        return 2
    return run(target, command)


if __name__ == "__main__":
    raise SystemExit(main())
