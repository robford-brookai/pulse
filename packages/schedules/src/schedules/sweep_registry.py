"""Sweep registry derived from the catalog, never hand-listed (design decision 1, task 1.1).

`build_registry` maps every catalog family to exactly one sweep kind from its `ownership`:
`recorded` (an external system of record adjudicates and exports) gets `export_diff`, the
existing consent sweep's kind; `ledger` (the ledger itself is the record) gets
`projection_conformance`, the referee that never writes (spec: "A ledger-owned family's sweep
never writes the ledger"). A family whose ownership is neither is refused at load, naming the
family and the value, rather than silently skipped — a catalog release that adds a family this
way is caught here, not downstream in a job that has nothing to dispatch it to.

The mapping itself (`family -> ownership`) is kept separate from `pulse_core.catalog_gen`'s typed
`Catalog.subjects`, whose `SubjectSpec.ownership` is already a closed `Literal["ledger",
"recorded"]` — a catalog file with any other value never reaches this module in production, since
`load_catalog` rejects it first. The registry validates the mapping again anyway, on plain
strings, so the "unknown ownership" refusal is this module's own behavior (testable without a
malformed catalog file) and stays correct if `catalog_gen`'s schema ever loosens.

`Consumer` (design decision 6) is the registry's other shape: a named reader of one or more
families, `cite_field=None` marking it uncitable (no `ledger_seq` to check `lag` against — it is
reported as its own class, not compared as agreement/divergence). No consumers are registered by
this task; wave 2 does that once the readers (1.3) exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pulse_core.catalog_gen import load_catalog

#: The two sweep kinds a family can be assigned (design decision 1). No third kind exists: a
#: family is either policed by an external system of record's export, or by the ledger itself.
SweepKind = Literal["export_diff", "projection_conformance"]

_SWEEP_KIND_BY_OWNERSHIP: dict[str, SweepKind] = {
    "recorded": "export_diff",
    "ledger": "projection_conformance",
}


class UnknownOwnershipError(ValueError):
    """A catalog family's `ownership` is neither `recorded` nor `ledger`.

    Raised at registry load, naming both the family and the offending value, so the failure
    reads directly from the exception rather than a caller having to re-derive which family
    broke.
    """

    def __init__(self, family: str, ownership: str) -> None:
        self.family = family
        self.ownership = ownership
        super().__init__(
            f"family {family!r} has ownership {ownership!r}; the sweep registry only knows "
            "'recorded' (-> export_diff) and 'ledger' (-> projection_conformance)"
        )


@dataclass(frozen=True)
class Family:
    """One catalog family and the sweep kind its ownership derives (design decision 1)."""

    name: str
    ownership: str
    sweep_kind: SweepKind


@dataclass(frozen=True)
class Consumer:
    """One reader of ledger state a sweep compares against (design decision 6).

    `cite_field=None` marks the consumer uncitable — its rows carry no `ledger_seq` a sweep can
    check for `lag`, so it is reported as its own class (`uncitable`) rather than compared as
    agreement or divergence. `reader` is typed loosely (`object`) because the reader
    implementations (`LedgerStateReader`, `BoardReader`, ...) are task 1.3's, not this one's.
    """

    name: str
    families: tuple[str, ...]
    reader: object
    cite_field: str | None
    freshness_budget_s: int
    owning_change: str | None = None

    @property
    def uncitable(self) -> bool:
        return self.cite_field is None


def build_registry(family_ownership: Mapping[str, str] | None = None) -> dict[str, Family]:
    """Build the family -> sweep-kind registry.

    `family_ownership` defaults to the released catalog's `subjects`, keyed by family name to
    `ownership` value (never a hand-kept list, per design decision 1). Pass an explicit mapping
    only to test the refusal path or another catalog snapshot; production callers take the
    default.
    """
    if family_ownership is None:
        family_ownership = {name: spec.ownership for name, spec in load_catalog().subjects.items()}

    registry: dict[str, Family] = {}
    for name, ownership in family_ownership.items():
        try:
            sweep_kind = _SWEEP_KIND_BY_OWNERSHIP[ownership]
        except KeyError:
            raise UnknownOwnershipError(name, ownership) from None
        registry[name] = Family(name=name, ownership=ownership, sweep_kind=sweep_kind)
    return registry
