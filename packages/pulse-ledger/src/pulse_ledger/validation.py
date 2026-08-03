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


def require_catalog_version(configured: str) -> None:
    """Boot-time guard: refuse to run against a catalog release the tables were not built from."""
    if configured != CATALOG_VERSION:
        raise CatalogVersionMismatchError(configured=configured, generated=CATALOG_VERSION)
