"""PULSE billing engine — event-driven eligibility/coverage rule evaluation.

Scaffold only (connector-pattern task 3.1): the package's own Postgres store
(``infra/postgres``, schema ``billing_engine``) and the shadow-ledger gate that keeps it from
becoming a second state of record (design.md decision 5, risk "Engine state store becomes a
shadow ledger"). Fact folding, rule evaluation, and declare-back land in later waves.
"""

from __future__ import annotations
