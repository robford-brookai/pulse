"""Normalize GitHub webhook payloads to Ocean event format."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def normalize_event(raw: dict, gh_event: str) -> dict | None:
    """Map a GitHub webhook payload to an Ocean signal event.

    Returns None for unsupported event types.
    """
    if gh_event == "pull_request":
        return _normalize_pr(raw)
    if gh_event == "push":
        return _normalize_push(raw)
    return None


def _normalize_pr(raw: dict) -> dict | None:
    action = raw.get("action", "")
    pr = raw.get("pull_request", {})
    repo_name = raw.get("repository", {}).get("full_name", "unknown")
    pr_number = pr.get("number", 0)

    if action == "opened":
        event_type = "pr.opened"
    elif action == "closed" and pr.get("merged"):
        event_type = "pr.merged"
    elif action == "closed":
        event_type = "pr.closed"
    else:
        return None

    entity_id = f"{repo_name}#{pr_number}"
    sender = raw.get("sender", {})

    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "source_system": "github",
        "entity_type": "pull_request",
        "entity_id": entity_id,
        "correlation_id": str(uuid4()),
        "actor_id": sender.get("login"),
        "payload": {
            "repo": repo_name,
            "pr_number": pr_number,
            "title": pr.get("title", ""),
            "author": pr.get("user", {}).get("login", ""),
            "base_branch": pr.get("base", {}).get("ref", ""),
            "head_branch": pr.get("head", {}).get("ref", ""),
        },
    }


def _normalize_push(raw: dict) -> dict | None:
    repo_name = raw.get("repository", {}).get("full_name", "unknown")
    head_sha = raw.get("after", "")
    if not head_sha:
        return None

    entity_id = f"{repo_name}@{head_sha[:12]}"
    commits = raw.get("commits", [])
    sender = raw.get("sender", {})

    return {
        "event_id": str(uuid4()),
        "event_type": "commit.pushed",
        "schema_version": "1.0.0",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "source_system": "github",
        "entity_type": "commit",
        "entity_id": entity_id,
        "correlation_id": str(uuid4()),
        "actor_id": sender.get("login"),
        "payload": {
            "repo": repo_name,
            "ref": raw.get("ref", ""),
            "head_sha": head_sha,
            "commit_count": len(commits),
            "pusher": raw.get("pusher", {}).get("name", ""),
        },
    }
