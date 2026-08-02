"""Tests for Linear issue -> Ocean ticket event normalization."""

from __future__ import annotations

import pytest


def _make_issue(
    *,
    priority: int = 3,
    labels: list[dict] | None = None,
    url: str = "https://linear.app/brook/issue/BROOK-42",
    title: str = "Test issue",
    assignee: dict | None = None,
) -> dict:
    issue = {
        "id": "issue-uuid-1",
        "title": title,
        "priority": priority,
        "url": url,
        "labels": labels or [],
    }
    if assignee is not None:
        issue["assignee"] = assignee
    return issue


class TestPriorityMapping:
    """Linear numeric priority maps to Ocean unified priority scale."""

    @pytest.mark.parametrize(
        ("linear_priority", "expected"),
        [
            (1, "critical"),
            (2, "high"),
            (3, "medium"),
            (4, "low"),
            (0, "low"),
        ],
    )
    def test_priority_mapping(self, linear_priority, expected):
        from src.normalizer import normalize_issue

        issue = _make_issue(priority=linear_priority, labels=[{"name": "ocean"}])
        event = normalize_issue(issue, "create")
        assert event is not None
        assert event["payload"]["priority"] == expected


class TestCategoryFromLabels:
    """Linear labels map to Ocean ticket categories."""

    @pytest.mark.parametrize(
        ("label_name", "expected_category"),
        [
            ("device", "device_issue"),
            ("Device", "device_issue"),
            ("activation", "patient_activation"),
            ("clinical", "clinical_support"),
            ("engineering", "engineering_it"),
        ],
    )
    def test_category_from_labels(self, label_name, expected_category):
        from src.normalizer import normalize_issue

        issue = _make_issue(labels=[{"name": "ocean"}, {"name": label_name}])
        event = normalize_issue(issue, "create")
        assert event is not None
        assert event["payload"]["category"] == expected_category

    def test_no_matching_label_defaults_engineering(self):
        from src.normalizer import normalize_issue

        issue = _make_issue(labels=[{"name": "ocean"}, {"name": "random-label"}])
        event = normalize_issue(issue, "create")
        assert event is not None
        assert event["payload"]["category"] == "engineering_it"


class TestSourceUrl:
    """Linear issue URL included as source_url in payload."""

    def test_issue_url_in_payload(self):
        from src.normalizer import normalize_issue

        url = "https://linear.app/brook/issue/BROOK-99"
        issue = _make_issue(url=url, labels=[{"name": "ocean"}])
        event = normalize_issue(issue, "create")
        assert event is not None
        assert event["payload"]["source_url"] == url


class TestAssignee:
    """Linear assignee maps to auto_claim_user."""

    def test_assignee_maps_to_auto_claim(self):
        from src.normalizer import normalize_issue

        issue = _make_issue(
            labels=[{"name": "ocean"}],
            assignee={"id": "user-1", "name": "Jane Doe"},
        )
        event = normalize_issue(issue, "create")
        assert event is not None
        assert event["payload"]["auto_claim_user"] == "Jane Doe"

    def test_no_assignee_no_auto_claim(self):
        from src.normalizer import normalize_issue

        issue = _make_issue(labels=[{"name": "ocean"}])
        event = normalize_issue(issue, "create")
        assert event is not None
        assert "auto_claim_user" not in event["payload"] or event["payload"].get("auto_claim_user") is None


class TestActionFiltering:
    """Only create and update actions produce events."""

    def test_delete_action_returns_none(self):
        from src.normalizer import normalize_issue

        issue = _make_issue(labels=[{"name": "ocean"}])
        assert normalize_issue(issue, "remove") is None

    def test_create_action_returns_event(self):
        from src.normalizer import normalize_issue

        issue = _make_issue(labels=[{"name": "ocean"}])
        event = normalize_issue(issue, "create")
        assert event is not None
        assert event["event_type"] == "ticket.create.requested"
