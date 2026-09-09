"""Tests for the Hasura metadata builder's `patients` select-only permissions.

Spec (patient-state-projection, "Only the ledger projection mints or updates a patient row"):
the database role every non-projection service uses SHALL hold select-only privileges on
`patients` (design.md decision 4 — the grant half of read-only enforcement; the gate half is
`tests/gates/test_patients_read_only.py`). Loaded by file path: `infra/hasura/apply_metadata.py`
is a standalone script, not a package member.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "infra" / "hasura" / "apply_metadata.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("apply_metadata", SOURCE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


apply_metadata = _load_module()


def test_every_service_role_gets_a_patients_select_permission():
    payloads = apply_metadata.build_patients_select_permission_payloads()
    roles = {payload["args"]["role"] for payload, _label in payloads}

    assert roles == set(apply_metadata.SERVICE_ROLES)
    assert len(payloads) == len(apply_metadata.SERVICE_ROLES)


def test_patients_select_permission_is_select_only_on_patients():
    for payload, _label in apply_metadata.build_patients_select_permission_payloads():
        assert payload["type"] == "pg_create_select_permission"
        assert payload["args"]["table"] == {"schema": "public", "name": "patients"}


def test_patients_select_permission_columns_cover_ledger_seq_and_every_read_surface_column():
    # slack-bot's /ocean patient command reads ledger_seq (#439); dropping it from the grant
    # would 403 that query on a real Hasura role even though the code and the fixture are fine.
    required = {"patient_id", "clinic_id", "enrollment_status", "enrolled_at", "updated_at", "ledger_seq"}

    for payload, _label in apply_metadata.build_patients_select_permission_payloads():
        columns = set(payload["args"]["permission"]["columns"])
        assert required <= columns, f"missing {required - columns} for role {payload['args']['role']!r}"


def test_patients_select_permission_has_no_row_filter():
    # `filter: {}` is unrestricted-rows, column-restricted-only — the grant is about write access,
    # not row visibility; a narrower filter isn't this decision's job.
    for payload, _label in apply_metadata.build_patients_select_permission_payloads():
        assert payload["args"]["permission"]["filter"] == {}


def test_table_and_relationship_payloads_are_unchanged():
    # The permission grant is additive: tracking tables and wiring relationships stay exactly
    # what they were before this change.
    table_payloads = [p for p, _label in apply_metadata.build_table_payloads()]
    assert table_payloads == [
        {"type": "pg_track_table", "args": {"source": "default", "table": {"schema": "public", "name": table}}}
        for table in apply_metadata.ALL_TABLES
    ]

    array_payloads = [p for p, _label in apply_metadata.build_array_relationship_payloads()]
    assert len(array_payloads) == len(apply_metadata.ARRAY_RELATIONSHIPS)
    assert all(p["type"] == "pg_create_array_relationship" for p in array_payloads)

    object_payloads = [p for p, _label in apply_metadata.build_object_relationship_payloads()]
    assert len(object_payloads) == len(apply_metadata.OBJECT_RELATIONSHIPS)
    assert all(p["type"] == "pg_create_object_relationship" for p in object_payloads)
