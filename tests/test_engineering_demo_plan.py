"""Ensure the demo plan has complete executable ownership and a valid task DAG."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGE = ROOT / "openspec/changes/engineering-demo"


def test_scenario_coverage_and_dependencies():
    spec = (CHANGE / "specs/engineering-demo/spec.md").read_text()
    tasks = (CHANGE / "tasks.md").read_text()
    coverage = json.loads((CHANGE / "traceability.json").read_text())
    scenarios = re.findall(r"^#### Scenario: (.+)$", spec, re.M)
    ids = re.findall(r"^- \[ \] (\d+\.\d+) ", tasks, re.M)
    assert set(coverage) == set(scenarios)
    assert {item for owners in coverage.values() for item in owners} == set(ids)
    assert all(coverage.values())
    seen = set()
    for task, block in zip(ids, re.split(r"^- \[ \] \d+\.\d+ ", tasks, flags=re.M)[1:], strict=True):
        dependencies = re.search(r"deps: ([^|]+)", block).group(1).strip()
        assert "Tests:" in block
        if dependencies != "—":
            assert set(dependencies.split(", ")) <= seen
        seen.add(task)
