"""Verdict type → rule module registry (billing-connector task 1.3).

Design decision 3 (`openspec/changes/billing-connector/design.md`): the connector evaluates
whatever this module lists, never a hardcoded name or count of its own — "adding a type is a
reviewed edit to the registry plus a rule module with lineage, never a connector change." This
module is additive to `packages/billing`, not part of the connector package, so the connector
never imports a rule module by name (spec: "The connector evaluates the registered verdict
types").

`tests/test_rule_port_lineage.py` (the "lineage gate", connector-pattern task 3.3) already pins
the portable set as `PORTED_VERDICT_TYPES` — today `{"billing_eligibility"}`; the other two
registered verdict types, `coverage_eligibility` and `benefits_verification`, have no dbt source
in the pinned scope and so no module (`billing.rules.__init__`). That gate asserts
`VERDICT_TYPES` names exactly its own `PORTED_VERDICT_TYPES`, and `packages/billing/tests/
test_registry.py` asserts it names exactly `billing.rules.__all__` — two independent checks the
same fact must survive, so a rule module and a registry entry can never drift apart unnoticed.
`VERDICT_TYPES` maps each shipped module's own `VERDICT_TYPE` constant to that module.
"""

from __future__ import annotations

from types import ModuleType

from billing.rules import billing_eligibility

#: Verdict type name -> the pure rule module that decides it (spec: "The connector SHALL refuse
#: to start if a registered type has no rule module or a rule module is unregistered"). Iterating
#: this mapping yields its keys, the registered verdict-type set `Config.verdict_types()`
#: (`billing_connector.config`) reads.
VERDICT_TYPES: dict[str, ModuleType] = {
    billing_eligibility.VERDICT_TYPE: billing_eligibility,
}

__all__ = ["VERDICT_TYPES"]
