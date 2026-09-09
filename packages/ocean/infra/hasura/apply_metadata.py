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

# Every service role that reaches Hasura's GraphQL API. `patients` is projected by
# handlers/patient_state.py alone (design.md decision 4) — no role here, including
# graph-projection's own, gets anything but select on it; the projection writes through a direct
# database session, never through Hasura, so it needs no elevated grant to do its job.
SERVICE_ROLES = [
    "graph-projection",
    "control-plane",
    "slack-bot",
    "impilo-connector",
    "stacte-bridge",
    "sim-driver",
]

# All columns on `patients` (infra/postgres/versions/0003_graph_tables.py, 0021_patients_ledger_seq.py).
# Select-only permissions list columns explicitly rather than granting "*" so a future column
# addition is a reviewed decision, not an automatic grant; `ledger_seq` is in this list because
# slack-bot's `/ocean patient` command reads it (services/slack-bot/src/slash_commands.py).
PATIENTS_SELECT_COLUMNS = [
    "patient_id",
    "clinic_id",
    "enrollment_status",
    "enrolled_at",
    "updated_at",
    "last_event_id",
    "ledger_seq",
]


def build_table_payloads() -> list[tuple[dict, str]]:
    """`(payload, label)` for every `pg_track_table` call."""
    return [
        (
            {
                "type": "pg_track_table",
                "args": {"source": "default", "table": {"schema": "public", "name": table}},
            },
            f"track {table}",
        )
        for table in ALL_TABLES
    ]


def build_array_relationship_payloads() -> list[tuple[dict, str]]:
    """`(payload, label)` for every `pg_create_array_relationship` call."""
    payloads = []
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
        payloads.append((payload, f"{parent_table}.{rel_name}"))
    return payloads


def build_object_relationship_payloads() -> list[tuple[dict, str]]:
    """`(payload, label)` for every `pg_create_object_relationship` call."""
    payloads = []
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
        payloads.append((payload, f"{child_table}.{rel_name}"))
    return payloads


def build_patients_select_permission_payloads() -> list[tuple[dict, str]]:
    """`(payload, label)` for a `pg_create_select_permission` on `patients`, one per service role.

    Every role gets the same select-only permission — no role gets insert/update/delete — so the
    database grant enforces what the repository gate (`test_patients_read_only.py`) enforces in
    source: only the projection handler writes `patients` (design.md decision 4).
    """
    payloads = []
    for role in SERVICE_ROLES:
        payload = {
            "type": "pg_create_select_permission",
            "args": {
                "source": "default",
                "table": {"schema": "public", "name": "patients"},
                "role": role,
                "permission": {"columns": PATIENTS_SELECT_COLUMNS, "filter": {}},
            },
        }
        payloads.append((payload, f"patients select permission for role {role!r}"))
    return payloads


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
    failed = 0

    with httpx.Client() as client:
        print("Tracking tables...")
        for payload, label in build_table_payloads():
            ok = call_metadata(client, payload, label)
            if ok:
                tracked += 1
            else:
                failed += 1

        print("\nCreating array relationships...")
        for payload, label in build_array_relationship_payloads():
            ok = call_metadata(client, payload, label)
            if ok:
                tracked += 1
            else:
                failed += 1

        print("\nCreating object relationships...")
        for payload, label in build_object_relationship_payloads():
            ok = call_metadata(client, payload, label)
            if ok:
                tracked += 1
            else:
                failed += 1

        # Select-only permissions on `patients` — design.md decision 4, the second half of
        # read-only enforcement (the first half is the repository gate, test_patients_read_only.py).
        print("\nGranting select-only permissions on patients...")
        for payload, label in build_patients_select_permission_payloads():
            ok = call_metadata(client, payload, label)
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
