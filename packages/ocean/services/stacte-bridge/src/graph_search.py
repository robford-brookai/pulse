"""N-hop graph traversal for OCEAN operational graph entities.

Traverses the patient-centered graph:
  patient → alerts → tasks → interactions → outcomes

Returns a structured neighborhood dict for a given entity ID.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


async def get_entity_neighborhood(
    session,
    entity_id: str,
    hops: int = 2,
) -> dict[str, Any]:
    """Return up to `hops`-hop neighborhood for any entity.

    Resolution order:
      1. Check patients table → traverse outward
      2. Check alerts → get patient + tasks
      3. Check tasks → get alert + interactions
      4. Check interactions → get task + outcomes
      5. Check outcomes → get interaction

    Returns a dict with 'root', 'entity_type', and related entity lists.
    """
    # Try to resolve entity_id across all entity tables
    for entity_type, table, pk in [
        ("patient", "patients", "patient_id"),
        ("alert", "alerts", "alert_id"),
        ("task", "tasks", "task_id"),
        ("interaction", "interactions", "interaction_id"),
        ("outcome", "outcomes", "outcome_id"),
    ]:
        result = await session.execute(
            sa.text(f"SELECT * FROM {table} WHERE {pk} = :id"),  # noqa: S608
            {"id": entity_id},
        )
        row = result.fetchone()
        if row is not None:
            root = dict(row._mapping)
            log.info("entity_found", entity_type=entity_type, entity_id=entity_id)
            return await _build_neighborhood(session, entity_type, root, hops)

    return {"entity_id": entity_id, "entity_type": "unknown", "root": None, "related": {}}


async def _build_neighborhood(
    session,
    entity_type: str,
    root: dict,
    hops: int,
) -> dict[str, Any]:
    """Build the neighborhood graph starting from root."""
    neighborhood: dict[str, Any] = {
        "entity_type": entity_type,
        "root": root,
        "related": {},
    }

    if hops < 1:
        return neighborhood

    patient_id = root.get("patient_id") or (root.get("patient_id") if entity_type == "patient" else None)
    if entity_type == "patient":
        patient_id = root["patient_id"]

    if patient_id:
        # Fetch alerts for this patient
        alerts_result = await session.execute(
            sa.text("SELECT * FROM alerts WHERE patient_id = :pid ORDER BY created_at DESC LIMIT 20"),
            {"pid": patient_id},
        )
        alerts = [dict(r._mapping) for r in alerts_result.fetchall()]
        neighborhood["related"]["alerts"] = alerts

        if hops >= 2:
            # Fetch tasks for this patient
            tasks_result = await session.execute(
                sa.text("SELECT * FROM tasks WHERE patient_id = :pid ORDER BY created_at DESC LIMIT 20"),
                {"pid": patient_id},
            )
            tasks = [dict(r._mapping) for r in tasks_result.fetchall()]
            neighborhood["related"]["tasks"] = tasks

            # Fetch interactions for this patient
            interactions_result = await session.execute(
                sa.text(
                    "SELECT * FROM interactions WHERE patient_id = :pid "
                    "ORDER BY started_at DESC LIMIT 20"
                ),
                {"pid": patient_id},
            )
            interactions = [dict(r._mapping) for r in interactions_result.fetchall()]
            neighborhood["related"]["interactions"] = interactions

            if hops >= 3:
                # Fetch outcomes
                outcomes_result = await session.execute(
                    sa.text(
                        "SELECT * FROM outcomes WHERE patient_id = :pid "
                        "ORDER BY recorded_at DESC LIMIT 20"
                    ),
                    {"pid": patient_id},
                )
                neighborhood["related"]["outcomes"] = [
                    dict(r._mapping) for r in outcomes_result.fetchall()
                ]

    return neighborhood
