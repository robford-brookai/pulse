"""Tests for GitHub event normalization."""
from __future__ import annotations

import pytest


def _make_pr_raw(*, action: str = "opened", merged: bool = False, number: int = 42) -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": number,
            "title": "Add feature",
            "merged": merged,
            "user": {"login": "dev1"},
            "base": {"ref": "main"},
            "head": {"ref": "feature-x"},
        },
        "repository": {"full_name": "brookai/ocean"},
        "sender": {"login": "dev1"},
    }


def _make_push_raw(*, after: str = "abc123def456789", commits: int = 1) -> dict:
    return {
        "ref": "refs/heads/main",
        "after": after,
        "commits": [{"id": f"commit-{i}"} for i in range(commits)],
        "repository": {"full_name": "brookai/ocean"},
        "sender": {"login": "dev1"},
        "pusher": {"name": "dev1"},
    }


class TestPRNormalization:
    def test_pr_opened(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_pr_raw(action="opened"), "pull_request")
        assert event is not None
        assert event["event_type"] == "pr.opened"
        assert event["entity_type"] == "pull_request"
        assert event["entity_id"] == "brookai/ocean#42"
        assert event["source_system"] == "github"
        assert event["payload"]["repo"] == "brookai/ocean"
        assert event["payload"]["pr_number"] == 42

    def test_pr_merged(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_pr_raw(action="closed", merged=True), "pull_request")
        assert event is not None
        assert event["event_type"] == "pr.merged"

    def test_pr_closed_not_merged(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_pr_raw(action="closed", merged=False), "pull_request")
        assert event is not None
        assert event["event_type"] == "pr.closed"

    def test_unsupported_action_returns_none(self):
        from src.normalizer import normalize_event

        assert normalize_event(_make_pr_raw(action="labeled"), "pull_request") is None

    def test_actor_id_from_sender(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_pr_raw(), "pull_request")
        assert event["actor_id"] == "dev1"


class TestPushNormalization:
    def test_push_event(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_push_raw(), "push")
        assert event is not None
        assert event["event_type"] == "commit.pushed"
        assert event["entity_type"] == "commit"
        assert event["entity_id"] == "brookai/ocean@abc123def456"
        assert event["payload"]["commit_count"] == 1

    def test_push_empty_sha_returns_none(self):
        from src.normalizer import normalize_event

        assert normalize_event(_make_push_raw(after=""), "push") is None

    def test_push_multi_commit(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_push_raw(commits=5), "push")
        assert event["payload"]["commit_count"] == 5


class TestUnsupportedEvent:
    def test_unknown_event_returns_none(self):
        from src.normalizer import normalize_event

        assert normalize_event({"action": "created"}, "issues") is None
