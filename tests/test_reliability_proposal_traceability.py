"""Keep proposed acceptance scenarios tied to executable, acyclic task plans.

This validates planning evidence, not implementation completion. Archived changes
retain their traceability with their task plans, so normal archive does not break it.
"""

from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = runpy.run_path(str(ROOT / "scripts" / "dispatch_tasks.py"))
parse_tasks = DISPATCH["parse_tasks"]
validate = DISPATCH["validate"]
CHANGES = (
    "relay-fairness",
    "idempotency-integrity",
    "critical-path-verification",
    "observability",
    "environment-matrix",
    "connector-first-contribution",
)


def change_path(name: str) -> Path:
    active = ROOT / "openspec" / "changes" / name
    if active.is_dir():
        return active
    archives = list((ROOT / "openspec" / "changes" / "archive").glob(f"*-{name}"))
    assert len(archives) == 1, f"Expected active or one archived plan for {name}"
    return archives[0]


@pytest.mark.parametrize("name", CHANGES)
def test_every_scenario_and_task_has_traceable_acceptance(name: str) -> None:
    change = change_path(name)
    evidence = json.loads((change / "traceability.json").read_text())
    tasks = parse_tasks(change / "tasks.md")
    validate(tasks)
    task_ids = {task["key"] for task in tasks}
    assert task_ids, "A ready proposal cannot have an empty implementation plan"
    assert evidence["change"] == name
    actual_scenarios = {
        f"{spec.parent.name}/{scenario}"
        for spec in change.glob("specs/*/spec.md")
        for scenario in re.findall(r"^#### Scenario: (.+)$", spec.read_text(), re.MULTILINE)
    }
    mapping = evidence["scenarios"]
    assert set(mapping) == actual_scenarios, "Scenario added or renamed without task ownership"
    covered_tasks: set[str] = set()
    for scenario, owners in mapping.items():
        assert owners, f"Unowned scenario: {scenario}"
        assert set(owners) <= task_ids, f"Unknown task owner for {scenario}"
        covered_tasks.update(owners)
    assert covered_tasks == task_ids, "Task has no scenario acceptance coverage"


@pytest.mark.parametrize("name", CHANGES)
def test_live_acceptance_and_external_holds_are_explicit(name: str) -> None:
    change = change_path(name)
    evidence = json.loads((change / "traceability.json").read_text())
    tasks = parse_tasks(change / "tasks.md")
    by_id = {task["key"]: task for task in tasks}
    live = {task["key"] for task in tasks if not task["dispatchable"]}
    assert set(evidence["live_tasks"]) == live
    for task_id in live:
        assert by_id[task_id]["deps"], "A live run needs its reviewed artifact first"
        assert evidence["live_tasks"][task_id] == "github_issue_after_runbook_merge"
    for hold in evidence["external_holds"]:
        assert hold["tasks"] and set(hold["tasks"]) <= set(by_id)
        assert hold["evidence_required"].strip()
    if name == "environment-matrix":
        assert any(set(hold["tasks"]) == set(by_id) for hold in evidence["external_holds"])
    if name == "connector-first-contribution":
        assert evidence["acceptance_basis"] == "first_contribution_outcomes"
        assert evidence["resume_devex_audit_loop"] is False
