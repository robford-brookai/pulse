"""REST API endpoints for STACTE consumers.

Provides:
  GET  /patient/{patient_id}/summary  — graph summary for Vanna.ai training
  GET  /entity/{entity_id}            — single entity fetch by ID
  GET  /schema                        — OCEAN Postgres DDL as JSON for schema RAG
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, HTTPException

log = structlog.get_logger()

router = APIRouter()

# DDL summary for Vanna.ai text-to-sql schema training
_SCHEMA_SUMMARY = {
    "tables": [
        {
            "table": "patients",
            "description": "Root entity. patient_id (PK), clinic_id, enrollment_status, enrolled_at, updated_at",
        },
        {
            "table": "signals",
            "description": "Biometric signals. signal_id (PK), patient_id (FK), signal_type, value, unit, received_at, anomalous",
        },
        {
            "table": "alerts",
            "description": "Clinical alerts. alert_id (PK), patient_id (FK), alert_type, severity, status, source_system, created_at, updated_at",
        },
        {
            "table": "tasks",
            "description": "Care coordination tasks. task_id (PK), alert_id (FK), patient_id (FK), task_type, priority, status, assigned_to, created_at",
        },
        {
            "table": "interactions",
            "description": "Call interactions. interaction_id (PK), task_id (FK), patient_id (FK), interaction_type, outcome, started_at, completed_at",
        },
        {
            "table": "outcomes",
            "description": "Call outcomes. outcome_id (PK), interaction_id (FK), patient_id (FK), outcome_type, resolution_status, notes, recorded_at",
        },
        {
            "table": "ai_drafts",
            "description": "AI-generated outreach drafts. draft_id (PK), task_id (FK), patient_id, alert_id, draft_text, status, actor_id, created_at",
        },
        {
            "table": "patient_graph_summary",
            "description": "Materialized view. patient_id (PK), enrollment_status, alert_count, task_count, interaction_count, outcome_count, last_alert_at, last_call_at, alert_types[], outcome_types[]",
        },
    ],
    "relationships": [
        "patients → signals (patient_id)",
        "patients → alerts (patient_id)",
        "alerts → tasks (alert_id)",
        "tasks → interactions (task_id)",
        "interactions → outcomes (interaction_id)",
    ],
}


def get_session():
    """Dependency placeholder — replaced by main.py session injection."""
    raise NotImplementedError("Session injection not configured")


@router.get("/schema")
async def get_schema() -> dict:
    """Return OCEAN Postgres DDL summary for Vanna.ai schema training."""
    return _SCHEMA_SUMMARY


@router.get("/patient/{patient_id}/summary")
async def get_patient_summary(patient_id: str, session=Depends(get_session)) -> dict[str, Any]:
    """Return the patient_graph_summary materialized view row."""
    result = await session.execute(
        sa.text("SELECT * FROM patient_graph_summary WHERE patient_id = :pid"),
        {"pid": patient_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return dict(row._mapping)


@router.get("/entity/{entity_id}")
async def get_entity(entity_id: str, session=Depends(get_session)) -> dict[str, Any]:
    """Resolve an entity_id across all tables and return the matching row."""
    for table, pk in [
        ("alerts", "alert_id"),
        ("tasks", "task_id"),
        ("interactions", "interaction_id"),
        ("outcomes", "outcome_id"),
        ("patients", "patient_id"),
    ]:
        result = await session.execute(
            sa.text(f"SELECT * FROM {table} WHERE {pk} = :id"),
            {"id": entity_id},
        )
        row = result.fetchone()
        if row is not None:
            return {"entity_type": table, "entity": dict(row._mapping)}

    raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
