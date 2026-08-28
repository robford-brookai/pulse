"""The D18 breaking-change rule as a pure function over two loaded catalogs (catalog-authority 3.1).

Verbatim runtime-readiness §4.3: a release is breaking when it **removes a state**, **narrows a
ValueSet**, or **changes a transition's legality** — in either direction, because an added edge
invalidates the warehouse `Q_INVALID_TRANSITIONS` expectation and Twenty picklist behavior just
as a removed one does. Everything else is additive: new states, transitions targeting them, new
ValueSet codes, new commands, new programs.

`classify_release` takes two `Catalog` models and returns every finding, each naming what
changed. It reads nothing, writes nothing, and mutates neither input — task 3.2 composes it into
the `task check` ceremony gate (MAJOR bump + migration note) over the two newest manifest
versions.

Two reporting rules, both deliberate:

- **A removed state is the root cause of its own vanished edges.** Dropping `screened` also
  drops every edge touching it; reporting those separately would bury the state removal in
  noise. Edge findings are therefore raised only between states both versions declare. The
  classification is identical either way — a removed state is already breaking.
- **Removed commands and programs are not breaking by this rule.** §4.3 names three triggers and
  this function is verbatim; commands are producer surface and programs are configuration (I6),
  not the state vocabulary consumers pin to. If that scope is ever widened, it widens in §4.3
  first, then here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pulse_core.catalog_gen import Catalog

FindingKind = Literal["state_removed", "valueset_narrowed", "transition_removed", "transition_added"]

Edge = tuple[str, str, str]


@dataclass(frozen=True, order=True)
class BreakingFinding:
    """One reason a release is breaking. `names` is the identity, `message` is the human wording.

    Ordered so a classification renders deterministically: the ceremony gate and the release row
    both print these, and an unstable order would flap a byte-comparison test.
    """

    kind: FindingKind
    names: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ReleaseClassification:
    """The verdict for one release: breaking iff there is at least one finding."""

    findings: tuple[BreakingFinding, ...]

    @property
    def breaking(self) -> bool:
        return bool(self.findings)


def _states(catalog: Catalog) -> dict[str, frozenset[str]]:
    """Every declared state, per subject. A subject's states are its transition-table keys."""
    return {subject: frozenset(spec.transitions) for subject, spec in catalog.subjects.items()}


def _edges(catalog: Catalog) -> frozenset[Edge]:
    """Every legal transition as a `(subject, from_state, to_state)` triple."""
    return frozenset(
        (subject, state, target)
        for subject, spec in catalog.subjects.items()
        for state, targets in spec.transitions.items()
        for target in targets
    )


def _codes(catalog: Catalog) -> dict[str, frozenset[str]]:
    """Every ValueSet's code vocabulary. Displays are not part of the contract, only codes are."""
    return {name: frozenset(spec.codes) for name, spec in catalog.valuesets.items()}


def _removed_states(previous: Catalog, current: Catalog) -> list[BreakingFinding]:
    now = _states(current)
    return [
        BreakingFinding(
            kind="state_removed",
            names=(subject, state),
            message=f"state {subject}.{state} was removed — a consumer pinned to it has no landing place",
        )
        for subject, states in _states(previous).items()
        for state in sorted(states - now.get(subject, frozenset()))
    ]


def _narrowed_valuesets(previous: Catalog, current: Catalog) -> list[BreakingFinding]:
    now = _codes(current)
    return [
        BreakingFinding(
            kind="valueset_narrowed",
            names=(valueset, code),
            message=f"ValueSet {valueset} no longer carries code {code!r} — the set narrowed",
        )
        for valueset, codes in _codes(previous).items()
        for code in sorted(codes - now.get(valueset, frozenset()))
    ]


def _legality_changes(previous: Catalog, current: Catalog) -> list[BreakingFinding]:
    """Edges whose legality flipped, restricted to states both versions declare.

    An edge touching a state only one version has was never *illegal* in the other — it was
    undefined. That is why `received -> deferred` against a brand-new `deferred` is additive,
    while `received -> screened` between two long-declared states is a legality change.
    """
    before, after = _states(previous), _states(current)
    shared = {subject: states & after.get(subject, frozenset()) for subject, states in before.items()}

    def within_shared(edge: Edge) -> bool:
        subject, state, target = edge
        return {state, target} <= set(shared.get(subject, frozenset()))

    old_edges = frozenset(filter(within_shared, _edges(previous)))
    new_edges = frozenset(filter(within_shared, _edges(current)))

    findings = [
        BreakingFinding(
            kind="transition_removed",
            names=edge,
            message=f"transition {edge[0]}: {edge[1]} -> {edge[2]} was legal and is not anymore",
        )
        for edge in sorted(old_edges - new_edges)
    ]
    findings.extend(
        BreakingFinding(
            kind="transition_added",
            names=edge,
            message=f"transition {edge[0]}: {edge[1]} -> {edge[2]} was illegal and is now legal",
        )
        for edge in sorted(new_edges - old_edges)
    )
    return findings


def classify_release(previous: Catalog, current: Catalog) -> ReleaseClassification:
    """Classify `current` against `previous` under the §4.3 breaking-change rule.

    Pure: no I/O, no mutation of either catalog. Findings come back sorted, so the same pair of
    catalogs always renders the same list.
    """
    findings = [
        *_removed_states(previous, current),
        *_narrowed_valuesets(previous, current),
        *_legality_changes(previous, current),
    ]
    return ReleaseClassification(findings=tuple(sorted(findings)))
