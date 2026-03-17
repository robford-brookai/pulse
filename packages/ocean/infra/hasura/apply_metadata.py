"""Register all Ocean graph tables and relationships in Hasura v2.

Run by the hasura-init Docker Compose service after Hasura is healthy and
migrations have completed. Idempotent — safely re-run on every startup.
"""
from __future__ import annotations

import os
import sys

import httpx

HASURA_URL = os.environ.get("HASURA_URL", "http://hasura:8080")
HEADERS = {
    "X-Hasura-Admin-Secret": os.environ.get("HASURA_GRAPHQL_ADMIN_SECRET", "changeme_admin_secret"),
    "Content-Type": "application/json",
}

# All tables to track — events and audit_log may already be tracked (tolerated)
ALL_TABLES = [
    "events",
    "audit_log",
    "patients",
    "signals",
    "alerts",
    "tasks",
    "interactions",
    "outcomes",
    "patient_timeline",
    "connector_health",
    "simulations",
]

# Array relationships: parent_table → child table via FK column
# ("parent_table", "relationship_name", "child_table", "fk_column_on_child")
ARRAY_RELATIONSHIPS = [
    ("patients", "signals", "signals", "patient_id"),
    ("patients", "alerts", "alerts", "patient_id"),
    ("patients", "tasks", "tasks", "patient_id"),
    ("alerts", "tasks", "tasks", "alert_id"),
    ("tasks", "interactions", "interactions", "task_id"),
    ("interactions", "outcomes", "outcomes", "interaction_id"),
]

# Object relationships: child_table → parent via FK column
# ("child_table", "relationship_name", "fk_column_on_child")
OBJECT_RELATIONSHIPS = [
    ("signals", "patient", "patient_id"),
    ("alerts", "patient", "patient_id"),
    ("tasks", "alert", "alert_id"),
    ("tasks", "patient", "patient_id"),
    ("interactions", "task", "task_id"),
    ("outcomes", "interaction", "interaction_id"),
]


def call_metadata(client: httpx.Client, payload: dict, label: str) -> bool:
    """POST to Hasura metadata API. Returns True on success, False on ignored error."""
    try:
        resp = client.post(f"{HASURA_URL}/v1/metadata", json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        body = exc.response.text
        if "already tracked" in body or "already exists" in body:
            print(f"  [skip] {label} — already tracked/exists")
            return True
        print(f"  [error] {label}: {exc.response.status_code} — {body[:200]}")
        return False
    except Exception as exc:
        print(f"  [error] {label}: {exc}")
        return False


def main() -> int:
    tracked = 0
    skipped = 0
    failed = 0

    with httpx.Client() as client:
        # Track tables
        print("Tracking tables...")
        for table in ALL_TABLES:
            payload = {
                "type": "pg_track_table",
                "args": {
                    "source": "default",
                    "table": {"schema": "public", "name": table},
                },
            }
            ok = call_metadata(client, payload, f"track {table}")
            if ok:
                tracked += 1
            else:
                failed += 1

        # Array relationships
        print("\nCreating array relationships...")
        for parent_table, rel_name, child_table, fk_col in ARRAY_RELATIONSHIPS:
            payload = {
                "type": "pg_create_array_relationship",
                "args": {
                    "source": "default",
                    "table": {"schema": "public", "name": parent_table},
                    "name": rel_name,
                    "using": {
                        "foreign_key_constraint_on": {
                            "table": {"schema": "public", "name": child_table},
                            "columns": [fk_col],
                        }
                    },
                },
            }
            ok = call_metadata(client, payload, f"{parent_table}.{rel_name}")
            if ok:
                tracked += 1
            else:
                failed += 1

        # Object relationships
        print("\nCreating object relationships...")
        for child_table, rel_name, fk_col in OBJECT_RELATIONSHIPS:
            payload = {
                "type": "pg_create_object_relationship",
                "args": {
                    "source": "default",
                    "table": {"schema": "public", "name": child_table},
                    "name": rel_name,
                    "using": {"foreign_key_constraint_on": [fk_col]},
                },
            }
            ok = call_metadata(client, payload, f"{child_table}.{rel_name}")
            if ok:
                tracked += 1
            else:
                failed += 1

    print(f"\nSummary: {tracked} succeeded, {failed} failed")

    # Exit 1 only if ALL operations failed (network/connectivity error)
    if failed > 0 and tracked == 0:
        print("ERROR: All metadata operations failed — likely Hasura connectivity issue")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
