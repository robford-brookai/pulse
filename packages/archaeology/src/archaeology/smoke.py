"""Smoke CLI: ``python -m archaeology.smoke --list-collections``.

The exit status is BF-0b's access receipt: zero means the read-only seam
reached the cluster and listed collection names. Output is collection names
only — never field values, never documents, so nothing PHI-shaped can leave
the process through this command.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from pymongo.errors import PyMongoError

from archaeology.client import ArchaeologyConfig, ArchaeologyError, create_readonly_client


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[..., Any] = create_readonly_client,
    environ: dict[str, str] | None = None,
) -> int:
    """Run the smoke check. Returns the process exit status (0 = access receipt).

    ``client_factory`` and ``environ`` exist for tests, which fake the driver
    boundary — see tests/test_smoke.py.
    """
    parser = argparse.ArgumentParser(
        prog="python -m archaeology.smoke",
        description="Verify read-only access to the legacy Mongo cluster. Exit 0 is the receipt.",
    )
    parser.add_argument(
        "--list-collections",
        action="store_true",
        help="list collection names in the configured database (names only)",
    )
    args = parser.parse_args(argv)
    if not args.list_collections:
        parser.error("nothing to do: pass --list-collections")

    try:
        config = ArchaeologyConfig.from_env(environ)
        client = client_factory(config, environ=environ)
    except (ArchaeologyError, PyMongoError) as exc:
        print(f"smoke: {exc}", file=sys.stderr)
        return 1
    try:
        # Sorted so the receipt is deterministic; names only, nothing else.
        for name in sorted(client[config.database].list_collection_names()):
            print(name)
    except PyMongoError as exc:
        print(f"smoke: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via main() in tests
    sys.exit(main())
