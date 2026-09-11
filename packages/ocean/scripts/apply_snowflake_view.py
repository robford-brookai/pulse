#!/usr/bin/env python3
"""Apply a committed Snowflake view DDL file (task snowflake:stg-events).

`CREATE OR REPLACE VIEW` is idempotent by construction — re-running against an unchanged file is
a no-op. Credentials come from the environment, same key-pair pattern `warehouse-sync` and
`warehouse_smoke.py` use; never reached from `task check` (no Snowflake credentials in CI,
docs/contracts/consumes.md).

`SNOWFLAKE_ROLE` is optional: both `STREAMLINE.STG_EVENTS` views are `ACCOUNTADMIN`-owned, so the
warehouse-sync service credential (role `OCEAN_WRITER`, grants scoped to `STREAMLINE.OCEAN_RAW`
only) cannot apply this DDL — set `SNOWFLAKE_ROLE=ACCOUNTADMIN` (or whatever role owns the
`STG_EVENTS` schema) with an operator credential that carries it. See docs/runbooks/
reconciliation-sweeps.md and docs/runbooks/warehouse-sync-revival.md for the applying credential
and the follow-up grant. `SNOWFLAKE_WAREHOUSE` is optional too, defaulting to `OCEAN_WH`.

The Snowflake driver and `cryptography` are imported lazily inside `_connect_snowflake`, not at
module scope: `connect_kwargs` is exercised by `tests/unit/test_apply_snowflake_view.py`, which
runs in the same pytest session as `packages/pulse-core/tests/test_catalog_release_guard.py`'s
`test_no_snowflake_driver_is_imported_at_test_time` guard — importing the driver at module scope
would trip that guard the moment this module is loaded for its test.

Usage:
    uv run python scripts/apply_snowflake_view.py infra/snowflake/stg_events_events.sql
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path

DEFAULT_WAREHOUSE = "OCEAN_WH"


def connect_kwargs(env: Mapping[str, str]) -> dict:
    """Build the keyword arguments for `snowflake.connector.connect` from the environment.

    Pure and connection-free so it is unit-testable: fails by name (`KeyError`'s message
    names the missing variable) rather than the operator seeing a bare traceback.
    """
    missing = [
        name for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH") if name not in env
    ]
    if missing:
        raise KeyError(f"missing required environment variable(s): {', '.join(missing)}")

    kwargs: dict = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "warehouse": env.get("SNOWFLAKE_WAREHOUSE", DEFAULT_WAREHOUSE),
    }
    role = env.get("SNOWFLAKE_ROLE")
    if role:
        kwargs["role"] = role
    return kwargs


def _connect_snowflake():
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    kwargs = connect_kwargs(os.environ)
    key_path = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    pkb = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(private_key=pkb, **kwargs)


def apply_view(sql_path: Path) -> None:
    statement = sql_path.read_text()
    conn = _connect_snowflake()
    try:
        cur = conn.cursor()
        try:
            cur.execute(statement)
        finally:
            cur.close()
    finally:
        conn.close()
    print(f"Applied {sql_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sql_path", type=Path, help="Path to the committed view DDL file")
    args = parser.parse_args()
    if not args.sql_path.is_file():
        print(f"FAIL: no such file: {args.sql_path}", file=sys.stderr)
        sys.exit(1)
    apply_view(args.sql_path)


if __name__ == "__main__":
    main()
