"""Shipped verdict-type configuration — the relay's registered mart verdict types (task 2.2).

This module is the sole owner of the shipped entries (billing-state design decision 4): both
halves of the change ride the one existing relay, configuration-extended. Three verdict types are
registered, on the unchanged pinned eight-column mart contract:

- `billing_eligibility` → `billing_episode`: the program billing qualification verdict; positive
  qualifies the episode, negative disqualifies it (`qualified ⇄ not_qualified` is re-runnable
  until `reported`).
- `coverage_eligibility` → `coverage`: automated eligibility (a future 270/271 integration,
  distinguished by `rule_version`).
- `benefits_verification` → `coverage`: Billy's manual benefits verification today, the same
  machine — both coverage types map positive/negative to `verified_active`/`verified_inactive`.

`indeterminate` deliberately maps nowhere: an indeterminate verdict is evidence without
consequence — the verdict declares, no transition follows. QMB status, benefit categories, and
copay detail live in verdict payload and `lineage_ref`, never in the state vocabulary
(coverage-state spec).

A verdict type outside `SUBJECT_TYPE_BY_VERDICT` fails row validation before any API call
(`RowValidationError` naming the row) — pinned in `test_config.py` so a new mart verdict type
must be registered here, deliberately, before the relay will carry it.

The mappings are `MappingProxyType` so no caller can widen the registered surface at runtime;
registration is a reviewed edit to this file.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

#: Which ledger subject each registered mart `verdict_type` declares against.
SUBJECT_TYPE_BY_VERDICT: Mapping[str, str] = MappingProxyType({
    "billing_eligibility": "billing_episode",
    "coverage_eligibility": "coverage",
    "benefits_verification": "coverage",
})

#: Outcome → `to_state` for the paired `declare_transition` (design decision 3). Outcomes a type
#: does not map — `indeterminate` everywhere — submit the verdict only.
TRANSITION_BY_OUTCOME: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "billing_eligibility": MappingProxyType({
        "positive": "qualified",
        "negative": "not_qualified",
    }),
    "coverage_eligibility": MappingProxyType({
        "positive": "verified_active",
        "negative": "verified_inactive",
    }),
    "benefits_verification": MappingProxyType({
        "positive": "verified_active",
        "negative": "verified_inactive",
    }),
})
