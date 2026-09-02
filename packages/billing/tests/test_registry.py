"""`billing.rules.registry` — billing-connector task 1.3 (spec: "The connector evaluates the
registered verdict types").

`billing.rules.__all__` is the portable set: every rule module this package actually ships a
lineage-mapped port for (`billing.rules` module docstring; `tests/test_billing_eligibility.py`
carries the per-module lineage checks referenced there as the "lineage gate"). This test asserts
`VERDICT_TYPES` names exactly that set, keyed by each module's own `VERDICT_TYPE` constant, so a
future rule module landing in `billing.rules.__all__` without a matching registry entry — or a
registry entry with no module behind it — fails here rather than silently drifting (spec: "the
connector SHALL refuse to start if a registered type has no rule module or a rule module is
unregistered").
"""

from __future__ import annotations

import importlib

import billing.rules as rules_package
from billing.rules.registry import VERDICT_TYPES


def _portable_modules() -> dict[str, object]:
    """Every shipped rule module, keyed by its own `VERDICT_TYPE` — the ground truth
    `billing.rules.__all__` names."""
    return {
        importlib.import_module(f"billing.rules.{name}").VERDICT_TYPE: importlib.import_module(f"billing.rules.{name}")
        for name in rules_package.__all__
    }


class TestRegistryMatchesThePortableSet:
    def test_registry_names_exactly_the_shipped_modules(self) -> None:
        portable = _portable_modules()

        assert set(VERDICT_TYPES) == set(portable)

    def test_each_registry_entry_is_the_module_that_owns_its_verdict_type(self) -> None:
        portable = _portable_modules()

        for verdict_type, module in VERDICT_TYPES.items():
            assert module is portable[verdict_type]
            assert verdict_type == module.VERDICT_TYPE

    def test_registry_holds_the_one_shipped_module(self) -> None:
        from billing.rules import billing_eligibility

        assert {"billing_eligibility": billing_eligibility} == VERDICT_TYPES
