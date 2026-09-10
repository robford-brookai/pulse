"""Validate readiness planning boundaries without claiming runtime acceptance."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHANGE = ROOT / "openspec/changes/company-readiness"


def test_documentation_change_has_explicit_spec_exemption():
    config = yaml.safe_load((CHANGE / ".openspec.yaml").read_text())
    assert config["skip_specs"] is True
    assert not (CHANGE / "specs").exists()
    for artifact in ("proposal.md", "design.md", "tasks.md"):
        assert (CHANGE / artifact).read_text().strip()


def test_readiness_tasks_have_tests_and_prior_dependencies():
    tasks = (CHANGE / "tasks.md").read_text()
    blocks = re.split(r"^- \[ \] (\d+\.\d+) ", tasks, flags=re.M)
    seen = set()
    for task, body in zip(blocks[1::2], blocks[2::2], strict=True):
        assert "Tests:" in body
        match = re.search(r"deps: ([^|]+)", body)
        assert match is not None
        dependencies = match.group(1).strip()
        if dependencies != "—":
            assert set(dependencies.split(", ")) <= seen
        seen.add(task)
    assert len(seen) == 6
