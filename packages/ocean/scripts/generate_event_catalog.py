#!/usr/bin/env python
"""Emit the Terraform half of the event catalog from `ocean_broker.catalog`.

Writes `infra/terraform/generated/event_catalog.auto.tfvars.json`, which Terraform
auto-loads. The file is committed so a plan needs no code execution, and a unit
test fails if it drifts from the table.

    uv run python scripts/generate_event_catalog.py            # write
    uv run python scripts/generate_event_catalog.py --check    # verify, exit 1 if stale
"""

from __future__ import annotations

import argparse
import sys

from ocean_broker.catalog import TFVARS_RELATIVE_PATH, render_tfvars_json, tfvars_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed file is current instead of rewriting it",
    )
    args = parser.parse_args(argv)

    rendered = render_tfvars_json()
    path = tfvars_path()

    if args.check:
        current = path.read_text() if path.exists() else ""
        if current != rendered:
            print(f"{TFVARS_RELATIVE_PATH} is stale — rerun without --check", file=sys.stderr)
            return 1
        print(f"{TFVARS_RELATIVE_PATH} is current")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered)
    print(f"wrote {TFVARS_RELATIVE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
