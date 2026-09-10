"""Keep the source-contract plan's acceptance coverage and task graph executable."""

import json
import re
from pathlib import Path

CHANGE = Path(__file__).resolve().parents[1] / "openspec/changes/connector-source-contracts"


def test_source_contract_scenarios_have_task_and_future_test():
    spec = (CHANGE / "specs/connector-source-contracts/spec.md").read_text()
    tasks = (CHANGE / "tasks.md").read_text()
    mappings = json.loads((CHANGE / "traceability.json").read_text())["scenarios"]
    scenarios = re.findall(r"^#### Scenario: (.+)$", spec, re.M)
    task_ids = set(re.findall(r"^- \[ \] (\d+\.\d+) ", tasks, re.M))
    assert len(scenarios) == 10
    assert {row["scenario"] for row in mappings} == set(scenarios)
    assert len(mappings) == len(scenarios)
    assert {row["task"] for row in mappings} == task_ids
    for row in mappings:
        assert row["test"].startswith("tests/test_connector_source_")
        assert row["test"] in tasks


def test_source_contract_task_dependencies_are_acyclic_and_bounded():
    tasks = (CHANGE / "tasks.md").read_text()
    seen = set()
    for task_id, rest in re.findall(r"^- \[ \] (\d+\.\d+) (.+)$", tasks, re.M):
        deps = re.search(r"deps: ([^|\]]+)", rest)
        assert deps is not None
        assert deps.group(1).strip() == "none" or set(deps.group(1).strip().split(",")) <= seen
        assert "[model: sonnet |" in rest
        assert "lane: repo_change" in rest
        assert "max 2h" in rest
        seen.add(task_id)
    assert len(seen) == 9
