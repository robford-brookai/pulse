"""The kit reaches every connector on the next `uv sync`; a connector author needs to see what
changed before it does (devex-eight-2 task 2.2, connector-kit spec: "Kit change is announced").

`tests/scaffold/cat10_devex.py::test_kit_has_changelog_and_deprecation_policy` also asserts this,
plus a Deprecations section in the connector-kit spec — that half is the doc-updater's, proposed
in `HANDOFF.md`. This test covers the half this task owns: the CHANGELOG itself exists and starts
at the package's current version.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[3]
CHANGELOG = ROOT / "packages/pulse-core/CHANGELOG.md"


def test_changelog_exists_and_starts_at_the_current_version():
    assert CHANGELOG.is_file(), "packages/pulse-core/CHANGELOG.md is missing"
    pyproject = tomllib.loads((ROOT / "packages/pulse-core/pyproject.toml").read_text())
    current_version = pyproject["project"]["version"]

    text = CHANGELOG.read_text()
    versions = re.findall(r"^##\s*\[?([0-9]+\.[0-9]+\.[0-9]+)\]?", text, re.M)
    assert versions, "CHANGELOG has no version headings"
    assert current_version in versions, f"CHANGELOG does not carry an entry for the current version {current_version}"
