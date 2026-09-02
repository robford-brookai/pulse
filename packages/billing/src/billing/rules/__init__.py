"""Ported verdict rules — one pure module per verdict type (connector-pattern task 3.3).

Every module here is a port, not a rewrite: its logic comes from a dbt verdict model named in
`packages/billing/docs/rule-port-map.md` (task 1.2), and every dbt test that map assigns to it
has a named unit test in `packages/billing/tests`. `tests/test_rule_port_lineage.py` holds both
halves of that claim true.

**What this package deliberately does not compute.** The 1.2 map flags 65 of the 72 pinned dbt
objects `stays-mart-side`: their assertions bottom out in facts the pulse ledger does not carry
and has no committed plan to carry — per-day device reading counts and reading-source
classification (RPM 99453/99445/99454), CGM reading counts and note existence (95251),
monitoring-minute sessions and their deduplication, active-condition and care-plan-review counts
(PCM/CCM), approved-care-plan status (APCM G0556), clinic-level program-enablement flags, the
dbt pipeline's rolling 30-day period framing, EMR order dates, and source-table recency
(`verdict_run_audit`). Those rules stay in the warehouse; the engine does not approximate them,
because an approximated predicate writes wrong billing state continuously. Each exclusion is
named with its missing fact in the map — read it there, not here.

Two of the three registered verdict types (`coverage_eligibility`, `benefits_verification`) have
no dbt source in the pinned scope at all, so nothing ports to them and no module exists for
them. That is the map's finding, not an omission.

No monetary value enters or leaves any rule in this package: the surface carries qualification
facts only (`docs/contracts/billing-boundary.md`).
"""

from __future__ import annotations

from billing.rules import billing_eligibility

__all__ = ["billing_eligibility"]
