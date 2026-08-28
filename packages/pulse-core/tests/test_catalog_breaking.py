"""The D18 breaking-change rule: a pure classifier over two loaded catalogs.

Covers the `catalog-versioning` spec scenarios "A removed state classifies breaking", "A
narrowed ValueSet classifies breaking", "A transition legality change classifies breaking", and
"An additive release classifies non-breaking". The rule is verbatim runtime-readiness §4.3 —
state removed, ValueSet narrowed, transition legality changed in either direction.
"""

from __future__ import annotations

from typing import Any

from pulse_core.catalog_breaking import classify_release
from pulse_core.catalog_gen import Catalog, load_catalog

BASE: dict[str, Any] = {
    "catalog_version": "1.0.0",
    "subjects": {
        "referral": {
            "ownership": "ledger",
            "transitions": {
                "received": ["resolved", "closed"],
                "resolved": ["screened", "closed"],
                "screened": ["closed"],
                "closed": [],
            },
        },
    },
    "commands": {"record_referral": {"subject_type": "referral"}},
    "valuesets": {
        "referral_closure_reason": {
            "description": "Why a referral closed.",
            "codes": {"deceased": "Deceased", "duplicate": "Duplicate"},
        },
    },
    "programs": {"pcm": {"display_name": "Principal Care Management"}},
    "registry_subjects": ["person"],
}


def catalog(**overrides: Any) -> Catalog:
    """Build a valid catalog from BASE with whole sections replaced."""
    return Catalog.model_validate({**BASE, **overrides})


def subjects_with(transitions: dict[str, list[str]]) -> dict[str, Any]:
    return {"referral": {"ownership": "ledger", "transitions": transitions}}


# --- A removed state classifies breaking -------------------------------------------------


def test_dropped_state_classifies_breaking_naming_the_state() -> None:
    current = catalog(
        subjects=subjects_with({
            "received": ["resolved", "closed"],
            "resolved": ["closed"],
            "closed": [],
        }),
    )

    result = classify_release(catalog(), current)

    assert result.breaking
    assert [finding.kind for finding in result.findings] == ["state_removed"]
    assert result.findings[0].names == ("referral", "screened")
    assert "screened" in result.findings[0].message


def test_dropped_subject_reports_each_of_its_states_naming_the_subject() -> None:
    current = catalog(subjects={}, commands={"record_referral": {}})

    result = classify_release(catalog(), current)

    assert result.breaking
    assert {finding.names for finding in result.findings} == {
        ("referral", "received"),
        ("referral", "resolved"),
        ("referral", "screened"),
        ("referral", "closed"),
    }
    assert all(finding.kind == "state_removed" for finding in result.findings)


def test_a_removed_state_does_not_also_report_the_edges_it_took_with_it() -> None:
    """The removed state is the root cause; its edges are not separate findings."""
    current = catalog(
        subjects=subjects_with({
            "received": ["resolved", "closed"],
            "resolved": ["closed"],
            "closed": [],
        }),
    )

    result = classify_release(catalog(), current)

    assert all(finding.kind == "state_removed" for finding in result.findings)


# --- A narrowed ValueSet classifies breaking ---------------------------------------------


def test_removed_valueset_code_classifies_breaking_naming_set_and_code() -> None:
    current = catalog(
        valuesets={
            "referral_closure_reason": {
                "description": "Why a referral closed.",
                "codes": {"deceased": "Deceased"},
            },
        },
    )

    result = classify_release(catalog(), current)

    assert result.breaking
    assert [finding.kind for finding in result.findings] == ["valueset_narrowed"]
    assert result.findings[0].names == ("referral_closure_reason", "duplicate")
    assert "referral_closure_reason" in result.findings[0].message
    assert "duplicate" in result.findings[0].message


def test_a_wholly_removed_valueset_narrows_every_code_it_carried() -> None:
    current = catalog(valuesets={}, commands={"record_referral": {"subject_type": "referral"}})

    result = classify_release(catalog(), current)

    assert result.breaking
    assert {finding.names for finding in result.findings} == {
        ("referral_closure_reason", "deceased"),
        ("referral_closure_reason", "duplicate"),
    }


def test_a_changed_code_display_is_not_a_narrowing() -> None:
    """Codes are the vocabulary; a display string is not part of the consumer contract."""
    current = catalog(
        valuesets={
            "referral_closure_reason": {
                "description": "Closure reasons, reworded.",
                "codes": {"deceased": "Patient deceased", "duplicate": "Duplicate"},
            },
        },
    )

    assert classify_release(catalog(), current).findings == ()


# --- A transition legality change classifies breaking ------------------------------------


def test_removed_edge_classifies_breaking_naming_the_edge() -> None:
    current = catalog(
        subjects=subjects_with({
            "received": ["closed"],
            "resolved": ["screened", "closed"],
            "screened": ["closed"],
            "closed": [],
        }),
    )

    result = classify_release(catalog(), current)

    assert result.breaking
    assert [finding.kind for finding in result.findings] == ["transition_removed"]
    assert result.findings[0].names == ("referral", "received", "resolved")
    assert "received" in result.findings[0].message
    assert "resolved" in result.findings[0].message


def test_added_edge_between_existing_states_classifies_breaking_naming_the_edge() -> None:
    """Legality in either direction (§4.3): a previously illegal edge is now legal."""
    current = catalog(
        subjects=subjects_with({
            "received": ["resolved", "screened", "closed"],
            "resolved": ["screened", "closed"],
            "screened": ["closed"],
            "closed": [],
        }),
    )

    result = classify_release(catalog(), current)

    assert result.breaking
    assert [finding.kind for finding in result.findings] == ["transition_added"]
    assert result.findings[0].names == ("referral", "received", "screened")
    assert "received" in result.findings[0].message
    assert "screened" in result.findings[0].message


def test_a_removed_and_an_added_edge_each_name_their_edge() -> None:
    current = catalog(
        subjects=subjects_with({
            "received": ["closed"],
            "resolved": ["screened", "closed"],
            "screened": ["closed", "received"],
            "closed": [],
        }),
    )

    result = classify_release(catalog(), current)

    assert result.breaking
    assert {(finding.kind, finding.names) for finding in result.findings} == {
        ("transition_removed", ("referral", "received", "resolved")),
        ("transition_added", ("referral", "screened", "received")),
    }


# --- An additive release classifies non-breaking ------------------------------------------


def test_identical_catalogs_classify_non_breaking() -> None:
    result = classify_release(catalog(), catalog())

    assert not result.breaking
    assert result.findings == ()


def test_additive_release_classifies_non_breaking() -> None:
    """New states, transitions targeting them, ValueSet codes, and programs only."""
    current = catalog(
        catalog_version="1.1.0",
        subjects=subjects_with({
            "received": ["resolved", "closed", "deferred"],
            "resolved": ["screened", "closed", "deferred"],
            "screened": ["closed"],
            "deferred": ["closed"],
            "closed": [],
        }),
        commands={
            "record_referral": {"subject_type": "referral"},
            "defer_referral": {"subject_type": "referral"},
        },
        valuesets={
            "referral_closure_reason": {
                "description": "Why a referral closed.",
                "codes": {
                    "deceased": "Deceased",
                    "duplicate": "Duplicate",
                    "clinic_terminated": "Clinic terminated",
                },
            },
            "deferral_reason": {"description": "Why deferred.", "codes": {"capacity": "Capacity"}},
        },
        programs={
            "pcm": {"display_name": "Principal Care Management"},
            "ccm": {"display_name": "Chronic Care Management"},
        },
    )

    result = classify_release(catalog(), current)

    assert not result.breaking
    assert result.findings == ()


def test_a_wholly_new_subject_is_additive() -> None:
    current = catalog(
        subjects={
            **BASE["subjects"],
            "consent": {
                "ownership": "ledger",
                "transitions": {"requested": ["granted"], "granted": [], "revoked": []},
            },
        },
    )

    assert classify_release(catalog(), current).findings == ()


# --- Shape of the classifier ---------------------------------------------------------------


def test_findings_are_sorted_deterministically() -> None:
    current = catalog(
        subjects=subjects_with({"received": ["closed"], "closed": []}),
        valuesets={
            "referral_closure_reason": {"description": "Why a referral closed.", "codes": {"deceased": "Deceased"}},
        },
    )

    findings = classify_release(catalog(), current).findings

    assert list(findings) == sorted(findings)
    assert findings == classify_release(catalog(), current).findings


def test_the_classifier_does_not_mutate_its_inputs() -> None:
    previous, current = catalog(), catalog(subjects=subjects_with({"received": [], "closed": []}))
    before = (previous.model_dump(), current.model_dump())

    classify_release(previous, current)

    assert (previous.model_dump(), current.model_dump()) == before


def test_the_committed_catalog_classifies_non_breaking_against_itself() -> None:
    """The rule holds on the real authoritative file, not just constructed fixtures."""
    head = load_catalog()

    assert classify_release(head, head).findings == ()
