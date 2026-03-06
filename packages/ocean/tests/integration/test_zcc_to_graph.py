"""Integration: ZCC webhook → normalizer → graph-projection → Postgres.

Verifies INGEST-02 + ZCC-02 + ZCC-03 end-to-end with real Postgres:

1. Normalize a contact_center.engagement_ended payload using the production normalizer.
2. Call handle_call_completed directly with the normalized event and a real DB session.
3. Assert Postgres has:
   - 1 Interaction row with the correct interaction_id and task_id FK.
   - 1 Outcome row with outcome_type='call_completed' and resolution_status='resolved'.
"""
from __future__ import annotations

import pathlib
import sys

import pytest
import pytest_asyncio
import sqlalchemy as sa

_ROOT = pathlib.Path(__file__).parents[2]

# Integration conftest already added graph-projection + zcc-connector to sys.path.
# Import the modules needed — note: we import from src.* which resolves to graph-projection
# because it was added first in conftest.py.

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def seed_patient_and_task(postgres_container):
    """Synchronous setup of prerequisite rows (patient + task) needed for FK constraints."""
    import sqlalchemy as sa_sync
    from sqlalchemy import create_engine, text as sync_text

    url = postgres_container.get_connection_url()
    engine = sa_sync.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sync_text(
            "INSERT INTO patients (patient_id, clinic_id, enrollment_status, updated_at) "
            "VALUES ('pt-integ-001', 'clinic-1', 'active', NOW()) "
            "ON CONFLICT (patient_id) DO NOTHING"
        ))
        conn.execute(sync_text(
            "INSERT INTO alerts (alert_id, patient_id, alert_type, severity, status, "
            "source_system, created_at, updated_at, correlation_id) "
            "VALUES ('alert-integ-001', 'pt-integ-001', 'glucose_high', 'URGENT', 'open', "
            "'pocar', NOW(), NOW(), 'corr-001') "
            "ON CONFLICT (alert_id) DO NOTHING"
        ))
        conn.execute(sync_text(
            "INSERT INTO tasks (task_id, alert_id, patient_id, task_type, priority, status, "
            "created_at, updated_at) "
            "VALUES ('task-integ-001', 'alert-integ-001', 'pt-integ-001', 'outreach', 'high', "
            "'open', NOW(), NOW()) "
            "ON CONFLICT (task_id) DO NOTHING"
        ))
    engine.dispose()


@pytest.mark.asyncio
async def test_call_completed_projects_interaction_and_outcome(
    session_factory, seed_patient_and_task
):
    """Normalize a ZCC engagement_ended event and project it — verify Postgres rows."""
    # Import normalizer from zcc-connector — must use importlib to avoid src conflict
    import importlib.util

    zcc_normalizer_path = _ROOT / "services" / "zcc-connector" / "src" / "normalizer.py"
    spec = importlib.util.spec_from_file_location("zcc_normalizer", zcc_normalizer_path)
    zcc_normalizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zcc_normalizer)

    # Import graph-projection handlers — these import from src.* (graph-projection is first in path)
    from src.handlers.outcomes import handle_call_completed  # noqa: PLC0415

    zcc_payload = {
        "event": "contact_center.engagement_ended",
        "payload": {
            "object": {
                "engagement_id": "eng-integ-001",
                "id": "eng-integ-001",
                "assigned_to": {"id": "agent-integ-1"},
                "duration": 300,
                "disposition_name": "resolved",
                "patient_id": "pt-integ-001",
                "task_id": "task-integ-001",
            }
        },
    }

    normalized = zcc_normalizer.normalize_zcc_event(zcc_payload)
    assert normalized is not None
    assert normalized["event_type"] == "call.completed"

    # Project event into Postgres
    async with session_factory() as session:
        async with session.begin():
            await handle_call_completed(normalized, session)

    # Verify Interaction row
    async with session_factory() as session:
        result = await session.execute(
            sa.text("SELECT interaction_id, task_id FROM interactions WHERE interaction_id = :id"),
            {"id": "eng-integ-001"},
        )
        row = result.fetchone()

    assert row is not None, "Interaction row not found after handle_call_completed"
    assert row.task_id == "task-integ-001", (
        f"ZCC-02: task_id FK expected 'task-integ-001', got '{row.task_id}'"
    )

    # Verify Outcome row
    async with session_factory() as session:
        result = await session.execute(
            sa.text(
                "SELECT outcome_type, resolution_status FROM outcomes "
                "WHERE interaction_id = :id"
            ),
            {"id": "eng-integ-001"},
        )
        outcome_row = result.fetchone()

    assert outcome_row is not None, "Outcome row not found after handle_call_completed"
    assert outcome_row.outcome_type == "call_completed", (
        f"ZCC-03: outcome_type expected 'call_completed', got '{outcome_row.outcome_type}'"
    )
    assert outcome_row.resolution_status == "resolved", (
        f"ZCC-03: resolution_status expected 'resolved', got '{outcome_row.resolution_status}'"
    )


@pytest.mark.asyncio
async def test_call_missed_projects_no_contact_outcome(session_factory, seed_patient_and_task):
    """call.missed produces outcome with no_contact resolution_status."""
    import importlib.util

    zcc_normalizer_path = _ROOT / "services" / "zcc-connector" / "src" / "normalizer.py"
    spec = importlib.util.spec_from_file_location("zcc_normalizer_missed", zcc_normalizer_path)
    zcc_normalizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zcc_normalizer)

    from src.handlers.outcomes import handle_call_missed  # noqa: PLC0415

    zcc_payload = {
        "event": "contact_center.engagement_missed",
        "payload": {
            "object": {
                "engagement_id": "eng-integ-002",
                "id": "eng-integ-002",
                "assigned_to": {"id": "agent-integ-1"},
                "duration": 0,
                "disposition_name": "",
                "patient_id": "pt-integ-001",
                "task_id": "task-integ-001",
            }
        },
    }

    normalized = zcc_normalizer.normalize_zcc_event(zcc_payload)
    assert normalized is not None

    async with session_factory() as session:
        async with session.begin():
            await handle_call_missed(normalized, session)

    async with session_factory() as session:
        result = await session.execute(
            sa.text(
                "SELECT outcome_type, resolution_status FROM outcomes "
                "WHERE interaction_id = :id"
            ),
            {"id": "eng-integ-002"},
        )
        outcome_row = result.fetchone()

    assert outcome_row is not None
    assert outcome_row.outcome_type == "call_missed"
    assert outcome_row.resolution_status == "no_contact"
