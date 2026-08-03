"""Command validation core (3.1, DNA-788).

Legality against the generated adjacency for all six subject types, rejection carrying the
catalog reason + version, and the boot-time catalog-version guard (design decision 4 / D18).
"""

from __future__ import annotations

import pytest
from pulse_core.generated import CATALOG_VERSION
from pulse_ledger.validation import (
    CatalogVersionMismatchError,
    IllegalTransitionError,
    require_catalog_version,
    validate_transition,
)

# One legal/illegal pair per subject type (object model v0.7's six ledger-owned subjects).
LEGAL_TRANSITIONS = [
    ("billing_episode", "open", "qualified"),
    ("consent", "requested", "granted"),
    ("contract", "draft", "active"),
    ("device", "ordered", "shipped"),
    ("enrollment", "active", "on_hold"),
    ("referral", "received", "resolved"),
]

ILLEGAL_TRANSITIONS = [
    ("billing_episode", "reported", "qualified"),
    ("consent", "revoked", "granted"),
    ("contract", "terminated", "active"),
    ("device", "lost", "active"),
    ("enrollment", "ended", "active"),
    ("referral", "converted", "outreach"),
]


@pytest.mark.parametrize(("subject_type", "from_state", "to_state"), LEGAL_TRANSITIONS)
def test_legal_transition_passes_and_returns_catalog_version(subject_type: str, from_state: str, to_state: str) -> None:
    assert validate_transition(subject_type, from_state, to_state) == CATALOG_VERSION


@pytest.mark.parametrize(("subject_type", "from_state", "to_state"), ILLEGAL_TRANSITIONS)
def test_illegal_transition_rejected_with_reason_and_version(subject_type: str, from_state: str, to_state: str) -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        validate_transition(subject_type, from_state, to_state)
    err = excinfo.value
    assert err.subject_type == subject_type
    assert err.from_state == from_state
    assert err.to_state == to_state
    assert err.catalog_version == CATALOG_VERSION
    # The reason names the violated transition; the message carries the catalog version.
    assert subject_type in err.reason
    assert from_state in err.reason
    assert to_state in err.reason
    assert CATALOG_VERSION in str(err)


def test_qualified_not_qualified_reentry_is_legal_both_ways() -> None:
    assert validate_transition("billing_episode", "qualified", "not_qualified") == CATALOG_VERSION
    assert validate_transition("billing_episode", "not_qualified", "qualified") == CATALOG_VERSION


def test_reported_freezes_verdict_reentry_but_allows_close() -> None:
    with pytest.raises(IllegalTransitionError):
        validate_transition("billing_episode", "reported", "qualified")
    with pytest.raises(IllegalTransitionError):
        validate_transition("billing_episode", "reported", "not_qualified")
    assert validate_transition("billing_episode", "reported", "closed") == CATALOG_VERSION


def test_unknown_subject_type_rejected_with_version() -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        validate_transition("spaceship", "docked", "launched")
    assert "spaceship" in excinfo.value.reason
    assert excinfo.value.catalog_version == CATALOG_VERSION


def test_unknown_from_state_rejected() -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        validate_transition("enrollment", "hibernating", "active")
    assert "hibernating" in excinfo.value.reason


def test_unknown_to_state_rejected() -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        validate_transition("enrollment", "active", "ascended")
    assert "ascended" in excinfo.value.reason


def test_boot_accepts_matching_catalog_version() -> None:
    require_catalog_version(CATALOG_VERSION)


def test_boot_refuses_on_catalog_version_mismatch() -> None:
    with pytest.raises(CatalogVersionMismatchError) as excinfo:
        require_catalog_version("appendix-c-v0.1")
    err = excinfo.value
    assert err.configured == "appendix-c-v0.1"
    assert err.generated == CATALOG_VERSION
    assert "appendix-c-v0.1" in str(err)
    assert CATALOG_VERSION in str(err)
