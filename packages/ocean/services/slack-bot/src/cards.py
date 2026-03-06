"""Slack Block Kit card builders — stub. Implemented in 03-03."""
from __future__ import annotations


def alert_card(
    task_id: str,
    patient_hash: str,
    alert_type: str,
    severity: str,
    timestamp: str,
    ai_summary: str,
    hasura_url: str,
) -> list[dict]:
    """Build the initial alert card posted to care team channel.

    Returns a Block Kit blocks list. Stub — implemented in 03-03.
    """
    return []


def claimed_card(task_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after a task is claimed.

    Returns a Block Kit blocks list. Stub — implemented in 03-03.
    """
    return []


def resolved_card(task_id: str, actor_id: str) -> list[dict]:
    """Build the card shown after a task is resolved.

    Returns a Block Kit blocks list. Stub — implemented in 03-03.
    """
    return []
