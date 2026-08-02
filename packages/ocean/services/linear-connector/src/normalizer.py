"""Normalize Linear issue data to Ocean ticket event format."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

PRIORITY_MAP: dict[int, str] = {
    1: "critical",
    2: "high",
    3: "medium",
    4: "low",
    0: "low",
}

LABEL_CATEGORY_MAP: dict[str, str] = {
    "device": "device_issue",
    "activation": "patient_activation",
    "clinical": "clinical_support",
    "engineering": "engineering_it",
}

DEFAULT_CATEGORY = "engineering_it"


def _category_from_labels(labels: list[dict]) -> str:
    """Derive Ocean ticket category from Linear issue labels (case-insensitive)."""
    for label in labels:
        name = label.get("name", "").lower()
        for key, category in LABEL_CATEGORY_MAP.items():
            if key in name:
                return category
    return DEFAULT_CATEGORY


def normalize_issue(issue_data: dict, action: str) -> dict | None:
    """Map a Linear issue to an Ocean ticket.create.requested event.

    Returns None if the action is not create or update.
    """
    if action not in ("create", "update"):
        return None

    priority_num = issue_data.get("priority", 0)
    priority = PRIORITY_MAP.get(priority_num, "low")
    labels = issue_data.get("labels", [])
    category = _category_from_labels(labels)

    now = datetime.now(tz=UTC)

    payload: dict = {
        "category": category,
        "priority": priority,
        "description": issue_data.get("title", ""),
        "patient_id": "",
        "source_url": issue_data.get("url", ""),
        "task_ids": [],
        "alert_ids": [],
    }

    assignee = issue_data.get("assignee")
    if assignee and isinstance(assignee, dict):
        payload["auto_claim_user"] = assignee.get("name")

    return {
        "event_id": str(uuid4()),
        "event_type": "ticket.create.requested",
        "schema_version": "1.0.0",
        "timestamp": now.isoformat(),
        "source_system": "linear-connector",
        "entity_type": "ticket",
        "correlation_id": str(uuid4()),
        "payload": payload,
    }
