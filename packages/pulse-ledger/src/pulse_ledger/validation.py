"""Command validation core (pulse-ledger-core design decision 4).

Transition legality is decided against the catalog's generated adjacency
(`pulse_core.generated.TRANSITIONS`) at write time — an illegal transition is rejected with the
catalog reason and version, never accepted-and-flagged. The service refuses to boot when the
generated tables' version disagrees with the catalog release it is configured for (D18).
"""

from __future__ import annotations

from pulse_core.generated import CATALOG_VERSION, TRANSITIONS

#: The states a subject may legally *enter* the ledger at, derived from the generated adjacency:
#: a state with no incoming edge is an entry point. Deriving it beats hand-listing it — the
#: catalog stays the single source, and a seed edit cannot leave this table stale. Entering at any
#: other state is what the restricted `backfill_genesis` vocabulary is for (task 3.5), which is
#: why the forward path refuses it.
INITIAL_STATES: dict[str, frozenset[str]] = {
    subject_type: frozenset(state for state in adjacency if not any(state in targets for targets in adjacency.values()))
    for subject_type, adjacency in TRANSITIONS.items()
}

#: Subject types whose derived initial state is never itself declared — every other catalog
#: subject enters the ledger through an explicit genesis event that sets its entry state
#: (`open_billing_episode`, and the rest of this program's registration commands); `coverage` has
#: no such command (coverage-state spec: "no separate registration step, no manual minting"). A
#: type listed here may have its first-ever declaration land directly on any state the catalog
#: lets its derived initial state reach — `validate_first_transition` treats the initial state as
#: an implicit predecessor rather than requiring a writer to declare it first. Scoped narrowly:
#: listing a type here is a deliberate exception, not a general relaxation of the genesis rule.
IMPLICIT_MINT_SUBJECT_TYPES: frozenset[str] = frozenset({"coverage"})


class IllegalTransitionError(Exception):
    """A declared transition the catalog does not permit; carries reason + catalog version.

    `from_state` is `None` when the rejected declaration was a subject's first — there is no state
    it departs from.
    """

    def __init__(self, subject_type: str, from_state: str | None, to_state: str, reason: str) -> None:
        self.subject_type = subject_type
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        self.catalog_version = CATALOG_VERSION
        super().__init__(f"{reason} (catalog {CATALOG_VERSION})")


class CatalogVersionMismatchError(Exception):
    """The configured catalog release disagrees with the generated tables' version (D18)."""

    def __init__(self, configured: str, generated: str) -> None:
        self.configured = configured
        self.generated = generated
        super().__init__(
            f"configured catalog version {configured!r} does not match "
            f"generated tables' version {generated!r}; refusing to boot"
        )


def validate_subject_type(subject_type: str) -> dict[str, frozenset[str]]:
    """The catalog's adjacency for one subject type, or a rejection naming the catalog version.

    The floor under the read path as `validate_state_membership` is the floor under the write path:
    a read filtered on a subject type the catalog does not define is a caller bug, and answering it
    with an empty result set would let it pass as "no such subjects exist".
    """
    adjacency = TRANSITIONS.get(subject_type)
    if adjacency is None:
        raise IllegalTransitionError(
            subject_type,
            None,
            "",
            reason=f"unknown subject_type {subject_type!r}",
        )
    return adjacency


def validate_transition(subject_type: str, from_state: str, to_state: str) -> str:
    """Validate a declared transition against the generated adjacency.

    Returns the catalog version in force, which the commit path stamps on the event as
    `rule_version`. Raises `IllegalTransitionError` for an unknown subject type, an unknown
    state, or a transition absent from the adjacency.
    """
    adjacency = TRANSITIONS.get(subject_type)
    if adjacency is None:
        raise IllegalTransitionError(
            subject_type,
            from_state,
            to_state,
            reason=f"unknown subject_type {subject_type!r}",
        )
    if from_state not in adjacency:
        raise IllegalTransitionError(
            subject_type,
            from_state,
            to_state,
            reason=f"unknown state {from_state!r} for subject_type {subject_type!r}",
        )
    if to_state not in adjacency:
        raise IllegalTransitionError(
            subject_type,
            from_state,
            to_state,
            reason=f"unknown state {to_state!r} for subject_type {subject_type!r}",
        )
    if to_state not in adjacency[from_state]:
        raise IllegalTransitionError(
            subject_type,
            from_state,
            to_state,
            reason=(
                f"illegal transition for {subject_type!r}: {from_state!r} -> {to_state!r} "
                "is not in the catalog adjacency"
            ),
        )
    return CATALOG_VERSION


def validate_state_membership(subject_type: str, state: str) -> str:
    """Check that the catalog knows this subject type and this state, and nothing more.

    The floor under every write, including the ones that legitimately relax the entry-state rule:
    a backfill may anchor a subject part-way through its machine, but never at a state the catalog
    does not contain. Without this, a typo would land in `current_state` — plain `Text`, no check
    constraint — stamped with a `rule_version` claiming catalog conformance.
    """
    adjacency = TRANSITIONS.get(subject_type)
    if adjacency is None:
        raise IllegalTransitionError(
            subject_type,
            None,
            state,
            reason=f"unknown subject_type {subject_type!r}",
        )
    if state not in adjacency:
        raise IllegalTransitionError(
            subject_type,
            None,
            state,
            reason=f"unknown state {state!r} for subject_type {subject_type!r}",
        )
    return CATALOG_VERSION


def validate_genesis(subject_type: str, state: str) -> str:
    """Validate a subject's first state against the catalog's entry points.

    Returns the catalog version, as `validate_transition` does. Raises `IllegalTransitionError`
    with `from_state=None` when the subject would enter the ledger part-way through its own state
    machine — reconstructing history from an arbitrary state is the `backfill_genesis` path, not
    the forward one.
    """
    validate_state_membership(subject_type, state)
    if state not in INITIAL_STATES[subject_type]:
        entry_points = ", ".join(sorted(INITIAL_STATES[subject_type]))
        raise IllegalTransitionError(
            subject_type,
            None,
            state,
            reason=(
                f"illegal genesis for {subject_type!r}: {state!r} is not an entry state "
                f"in the catalog (entry states: {entry_points})"
            ),
        )
    return CATALOG_VERSION


def validate_first_transition(subject_type: str, to_state: str) -> str:
    """Validate a subject's very first state-bearing declaration.

    Ordinarily this is `validate_genesis`: the first declaration must land exactly on the
    catalog's entry state, the explicit registration event every other subject type carries. For
    a type in `IMPLICIT_MINT_SUBJECT_TYPES`, the derived initial state is never itself declared —
    so the first-ever transition may land on any state legally reachable from it, and the catalog
    validates the move as if departing from that implicit predecessor (coverage-state spec:
    "First declare mints and transitions"). No separate event is written for the implicit
    predecessor; the single declared event is the subject's only history.
    """
    if subject_type in IMPLICIT_MINT_SUBJECT_TYPES:
        entry_points = INITIAL_STATES.get(subject_type, frozenset())
        if to_state not in entry_points:
            (derived_initial,) = entry_points
            return validate_transition(subject_type, derived_initial, to_state)
    return validate_genesis(subject_type, to_state)


def require_catalog_version(configured: str) -> None:
    """Boot-time guard: refuse to run against a catalog release the tables were not built from."""
    if configured != CATALOG_VERSION:
        raise CatalogVersionMismatchError(configured=configured, generated=CATALOG_VERSION)
