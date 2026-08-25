#!/usr/bin/env python3
"""Apply a committed Snowflake view DDL file (task snowflake:stg-events).

`CREATE OR REPLACE VIEW` is idempotent by construction — re-running against an unchanged file is
a no-op. Credentials come from the environment, same key-pair pattern `warehouse-sync` and
`warehouse_smoke.py` use; never reached from `task check` (no Snowflake credentials in CI,
docs/contracts/consumes.md).

Usage:
    uv run python scripts/apply_snowflake_view.py infra/snowflake/stg_events_events.sql
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import snowflake.connector
from cryptography.hazmat.primitives import serialization


def _connect_snowflake() -> snowflake.connector.SnowflakeConnection:
    key_path = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    pkb = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=pkb,
        warehouse="OCEAN_WH",
    )


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
