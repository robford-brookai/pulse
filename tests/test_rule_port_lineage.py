"""The rule-port lineage gate (connector-pattern task 3.3).

Task 1.2 wrote the map; this gate holds the port to it, so the port stays a port and does not
drift into a re-imagining (spec: "Rules are ported with lineage, not re-imagined"):

1. Every module under `billing.rules` carries `RULE_VERSION = "pulse-<verdict-type>-v1"` and a
   docstring naming the dbt model it was ported from — and that model is one the map pins.
2. Every `<file>.py::<test_name>` counterpart the map names exists as a test function, so a
   renamed or deleted unit test breaks the build instead of silently orphaning a dbt rule.
3. The rules package covers exactly the verdict types the map marks portable — a `stays-mart-side`
   rule that grows a module here, or a ported rule that loses one, is a lineage break either way.
4. The module's verdict type is registered vocabulary (`verdict_relay.config`), so the engine
   declares a type the command API accepts.

Offline, no network, no credentials — reads the committed doc and imports the rule modules.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path
from types import ModuleType

import pytest
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT

REPO_ROOT = Path(__file__).resolve().parents[1]
BILLING_ROOT = REPO_ROOT / "packages" / "billing"
MAP_PATH = BILLING_ROOT / "docs" / "rule-port-map.md"
RULES_DIR = BILLING_ROOT / "src" / "billing" / "rules"
#: Bare filenames in the map resolve here — the package's own unit-test tree.
DEFAULT_TEST_DIR = BILLING_ROOT / "tests"

#: The verdict types the map marks portable within the pinned dbt scope. The map is explicit
#: that `coverage_eligibility` and `benefits_verification` have no dbt source in this scope at
#: all ("not a gap, just outside what this tree computes"), so the engine ports neither: a rule
#: module for either would be invented logic, which is exactly what this task must not produce.
PORTED_VERDICT_TYPES = frozenset({"billing_eligibility"})

#: The dbt models the map pins (mirrors `tests/test_rule_port_map.py::PINNED_MODELS`); a rule
#: module must name one of these as its source, not some model outside the ported scope.
PINNED_MODELS = frozenset({"verdict_billing_episode", "verdict_run_audit"})

#: `<file>.py::<test_name>` counterparts the map names that do not exist yet, each with the task
#: that creates it. A deferred entry must be genuinely absent — once its test lands, this list
#: must shrink or the gate fails, so the allowance cannot outlive the deferral.
DEFERRED_COUNTERPARTS = {
    "packages/billing/tests/test_engine.py::test_unchanged_facts_declare_nothing_new": "task 3.4 (evaluation to declare)",
}

#: A `path.py::test_name` reference anywhere in the map's prose or tables.
COUNTERPART_REF = re.compile(r"([A-Za-z0-9_./-]+\.py)::(test_[A-Za-z0-9_]+)")


def _map_text() -> str:
    return MAP_PATH.read_text(encoding="utf-8")


def _rule_modules() -> list[tuple[str, ModuleType]]:
    return [
        (info.name, importlib.import_module(f"billing.rules.{info.name}"))
        for info in pkgutil.iter_modules([str(RULES_DIR)])
        if not info.name.startswith("_")
    ]


def _resolve(path_text: str) -> Path:
    candidate = Path(path_text)
    if len(candidate.parts) == 1:
        return DEFAULT_TEST_DIR / candidate
    return REPO_ROOT / candidate


def _canonical(path_text: str, test_name: str) -> str:
    return f"{_resolve(path_text).relative_to(REPO_ROOT).as_posix()}::{test_name}"


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def _exists(path_text: str, test_name: str) -> bool:
    path = _resolve(path_text)
    return path.is_file() and test_name in _test_functions(path)


def test_rules_package_covers_exactly_the_ported_verdict_types() -> None:
    present = {name for name, _ in _rule_modules()}
    assert present == PORTED_VERDICT_TYPES, (
        f"billing.rules holds {sorted(present)}; the 1.2 map marks {sorted(PORTED_VERDICT_TYPES)} portable — "
        "a module for a stays-mart-side type is invented logic, a missing one is a verdict gap"
    )


@pytest.mark.parametrize("name", sorted(PORTED_VERDICT_TYPES))
def test_rule_module_carries_its_own_rule_version(name: str) -> None:
    module = importlib.import_module(f"billing.rules.{name}")
    assert f"pulse-{name.replace('_', '-')}-v1" == module.RULE_VERSION, (
        "a verdict must name its implementation unambiguously against the mart's versions"
    )


@pytest.mark.parametrize("name", sorted(PORTED_VERDICT_TYPES))
def test_rule_module_docstring_names_its_dbt_source(name: str) -> None:
    module = importlib.import_module(f"billing.rules.{name}")
    doc = module.__doc__ or ""
    named = {model for model in PINNED_MODELS if model in doc}
    assert named, (
        f"billing/rules/{name}.py's docstring names no pinned dbt model — a ported rule states "
        f"what it was ported from (one of {sorted(PINNED_MODELS)})"
    )
    assert "rule-port-map.md" in doc, f"billing/rules/{name}.py's docstring does not point back at the 1.2 map"


@pytest.mark.parametrize("name", sorted(PORTED_VERDICT_TYPES))
def test_rule_module_verdict_type_is_registered_vocabulary(name: str) -> None:
    module = importlib.import_module(f"billing.rules.{name}")
    assert module.VERDICT_TYPE in SUBJECT_TYPE_BY_VERDICT, (
        f"{module.VERDICT_TYPE} is not a registered verdict type — row validation rejects it before any API call"
    )
    assert SUBJECT_TYPE_BY_VERDICT[module.VERDICT_TYPE] == module.SUBJECT_TYPE


def test_every_mapped_counterpart_exists_as_a_test_function() -> None:
    refs = COUNTERPART_REF.findall(_map_text())
    assert refs, "the map names no unit-test counterparts — the port has no lineage to check"

    missing = [
        _canonical(path_text, test_name)
        for path_text, test_name in refs
        if not _exists(path_text, test_name) and _canonical(path_text, test_name) not in DEFERRED_COUNTERPARTS
    ]
    assert not missing, f"rule-port-map.md names counterpart(s) that do not exist: {missing}"


def test_deferred_counterparts_are_still_genuinely_absent() -> None:
    """Self-cleaning: once a deferred test lands, its allowance must be deleted, or the gate has
    quietly stopped checking a rule it is supposed to check."""
    landed = [ref for ref in DEFERRED_COUNTERPARTS if _exists(*ref.split("::"))]
    assert not landed, f"these counterparts now exist — remove them from DEFERRED_COUNTERPARTS: {landed}"


def test_deferred_counterparts_name_their_owning_task() -> None:
    for ref, reason in DEFERRED_COUNTERPARTS.items():
        assert re.search(r"task \d+\.\d+", reason), f"{ref}'s deferral does not name the task that lands it"


def test_stays_mart_side_rules_are_excluded_and_documented() -> None:
    """The map's exclusions are the port's exclusions: the rules package documents that it
    computes only what the map marks portable, and names where the rest stayed."""
    doc = (RULES_DIR / "__init__.py").read_text(encoding="utf-8")
    assert "stays-mart-side" in doc
    assert "rule-port-map.md" in doc
