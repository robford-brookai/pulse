"""Spec coverage — every `### Requirement` in the delta spec is named by at least one docstring
in the connector's own source tree (task 1.3, design.md decision 2: "docstrings naming the spec
requirement each satisfies").

This is a text-level check, not a semantic one: it proves no requirement was left undocumented
while the module bodies still raise `NotImplementedError`, not that the eventual implementation
is correct. Wave 1's own tests carry that weight per module.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC_PATH = _REPO_ROOT / "openspec" / "changes" / "billing-connector" / "specs" / "billing-connector" / "spec.md"
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "billing_connector"

_REQUIREMENT_HEADING = re.compile(r"^### Requirement: (.+)$", re.MULTILINE)


def _requirement_titles() -> list[str]:
    return _REQUIREMENT_HEADING.findall(_SPEC_PATH.read_text())


def _all_docstrings() -> str:
    """Every module, class, and function docstring under `src/billing_connector`, joined."""
    docstrings: list[str] = []
    for py_file in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        docstrings.append(ast.get_docstring(tree) or "")
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                docstrings.append(ast.get_docstring(node) or "")
    return "\n".join(docstrings)


class TestEveryRequirementIsNamed:
    def test_the_spec_has_requirements_to_check(self) -> None:
        assert _requirement_titles(), "no ### Requirement headings found — spec path is stale"

    def test_every_requirement_title_appears_in_a_docstring(self) -> None:
        joined = _all_docstrings()
        missing = [title for title in _requirement_titles() if title not in joined]
        assert not missing, f"requirements with no docstring naming them: {missing}"
