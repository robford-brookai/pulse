"""Command validation core (pulse-ledger-core design decision 4).

Transition legality is decided against the catalog's generated adjacency
(`pulse_core.generated.TRANSITIONS`) at write time — an illegal transition is rejected with the
catalog reason and version, never accepted-and-flagged. The service refuses to boot when the
generated tables' version disagrees with the catalog release it is configured for (D18).
"""

from __future__ import annotations

from pulse_core.generated import CATALOG_VERSION, TRANSITIONS


class IllegalTransitionError(Exception):
    """A declared transition the catalog does not permit; carries reason + catalog version."""

    def __init__(self, subject_type: str, from_state: str, to_state: str, reason: str) -> None:
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


def require_catalog_version(configured: str) -> None:
    """Boot-time guard: refuse to run against a catalog release the tables were not built from."""
    if configured != CATALOG_VERSION:
        raise CatalogVersionMismatchError(configured=configured, generated=CATALOG_VERSION)
