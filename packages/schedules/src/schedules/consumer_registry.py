"""Consumer registration (task 3.2, design.md decision 6): the day-one `Consumer` entries and the
registry x consumer matrix each `projection_conformance` sweep (task 2.1) runs against.

Three entries, none of them hand-listing families beyond what their own source already knows:

- **`twenty-board`** — the families the app projects, read through the projection's own read
  surface. Derived from `twenty_projection.apply`'s registered `BoardTarget`s (today: `V1_BOARD`,
  `enrollment` only), so a second board added there registers a second family here without this
  module changing. Citable (`cite_field="ledger_seq"`), 60 s freshness budget — the §1.5
  projection-freshness SLO.
- **`warehouse-landing`** — every family the registry assigned `projection_conformance`, read
  through the fold view (task 1.2's `SUBJECT_CURRENT_STATE`). Citable (`cite_field="seq"`, the
  fold view's own column name), 15-minute freshness budget by default, configurable per design
  decision 6.
- **`graph-projection-patients`** — `enrollment` only, uncitable (`cite_field=None`): reported as
  a class with its row count and `owning_change` set to `m1-retire-patient-state`, the change that
  retires it, never compared row by row (spec projection-conformance: "Consumers that cannot cite
  at all are reported as a class").

`build_consumers` takes readers as the caller's own (task 1.3's production readers, or a
`FixtureReader` in tests) — this module only decides which families each consumer is registered
against, never how a family is read. `consumers_by_family` is the matrix itself: every family
handed in mapped to the consumers registered against it, in registration order, with `()` for a
family no consumer named — `no_consumers`, which passes rather than diverges (design decision 6:
"A ledger family with zero consumers passes with `no_consumers`... it is not a divergence").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from twenty_projection.apply import V1_BOARD, BoardTarget

from schedules.sweep_registry import Consumer, Family

__all__ = [
    "BOARD_FRESHNESS_BUDGET_S",
    "BOARD_TARGETS",
    "DEFAULT_LANDING_FRESHNESS_BUDGET_S",
    "PATIENTS_OWNING_CHANGE",
    "board_families",
    "build_consumers",
    "consumers_by_family",
    "ledger_families",
]

#: Every board the app projects today (design decision 6: "the families the app projects") —
#: derived from the projection's own wiring, never a hand-kept list: a board added to
#: `twenty_projection.apply` adds a family here without this tuple changing by hand.
BOARD_TARGETS: tuple[BoardTarget, ...] = (V1_BOARD,)

#: The board's freshness budget (design decision 4: "60 s for the board (the §1.5
#: projection-freshness SLO)").
BOARD_FRESHNESS_BUDGET_S = 60

#: The landing's freshness budget: 15 minutes, configurable per family or per run (design
#: decision 4 and 6).
DEFAULT_LANDING_FRESHNESS_BUDGET_S = 15 * 60

#: The change that owns retiring graph-projection's `patients` table (design decision 6;
#: proposal.md "Cross-change").
PATIENTS_OWNING_CHANGE = "m1-retire-patient-state"


def board_families() -> tuple[str, ...]:
    """Families the app projects today: every registered board's `subject_type`, in registration
    order."""
    return tuple(target.subject_type for target in BOARD_TARGETS)


def ledger_families(registry: Mapping[str, Family]) -> tuple[str, ...]:
    """Every family the registry assigned `projection_conformance` — the only families a
    consumer registers against here. A `recorded` family keeps its own `export_diff` sweep
    (task 2.2) untouched; this registration never names one."""
    return tuple(sorted(name for name, family in registry.items() if family.sweep_kind == "projection_conformance"))


def build_consumers(
    registry: Mapping[str, Family],
    *,
    board_reader: object,
    landing_reader: object,
    patients_reader: object,
    landing_freshness_budget_s: int = DEFAULT_LANDING_FRESHNESS_BUDGET_S,
) -> tuple[Consumer, ...]:
    """The day-one consumer registration (design decision 6): `twenty-board`, `warehouse-landing`,
    `graph-projection-patients`, in that order.

    `registry` supplies the ledger family set `warehouse-landing` reads (via `ledger_families`);
    the readers are the caller's own — this function decides only which families each consumer is
    registered against.
    """
    return (
        Consumer(
            name="twenty-board",
            families=board_families(),
            reader=board_reader,
            cite_field="ledger_seq",
            freshness_budget_s=BOARD_FRESHNESS_BUDGET_S,
        ),
        Consumer(
            name="warehouse-landing",
            families=ledger_families(registry),
            reader=landing_reader,
            cite_field="seq",
            freshness_budget_s=landing_freshness_budget_s,
        ),
        Consumer(
            name="graph-projection-patients",
            families=("enrollment",),
            reader=patients_reader,
            cite_field=None,
            freshness_budget_s=landing_freshness_budget_s,
            owning_change=PATIENTS_OWNING_CHANGE,
        ),
    )


def consumers_by_family(
    consumers: Iterable[Consumer],
    families: Iterable[str],
) -> dict[str, tuple[Consumer, ...]]:
    """Every family in `families` mapped to the consumers registered against it, in registration
    order. A family no consumer named gets `()` — `no_consumers` (design decision 6), never a
    `KeyError` a caller has to guard against."""
    matrix: dict[str, list[Consumer]] = {family: [] for family in families}
    for consumer in consumers:
        for family in consumer.families:
            if family in matrix:
                matrix[family].append(consumer)
    return {family: tuple(entries) for family, entries in matrix.items()}
