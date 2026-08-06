"""The synthetic demographic fixture set loads and validates cleanly.

No live network, no `identity.normalize`/`identity.matcher` import — this only proves the
fixture shape is sound (task 2.2). Fixtures are pure data: no PHI, synthetic names and DOBs only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fixtures.loader import (
    FIXTURES_DIR,
    FixtureShapeError,
    list_case_files,
    load_all_cases,
    load_case,
)

EXPECTED_CASES = frozenset({
    "exact_identifier_hit",
    "composite_unique_hit",
    "mint_unknown_everything",
    "two_candidate_ambiguity",
    "near_miss_different_dob",
    "suffix_casing_pairs",
    "ambiguous_dob_format",
})


def test_every_required_case_is_present():
    cases = load_all_cases()
    assert cases.keys() >= EXPECTED_CASES


def test_loader_validates_every_fixture_file_without_error():
    files = list_case_files()
    assert len(files) == len(EXPECTED_CASES)
    for path in files:
        load_case(path)  # raises FixtureShapeError on a malformed file


def test_decision_cases_declare_a_valid_decision_and_rule_id():
    cases = load_all_cases()
    for name in (
        "exact_identifier_hit",
        "composite_unique_hit",
        "mint_unknown_everything",
        "two_candidate_ambiguity",
        "near_miss_different_dob",
    ):
        case = cases[name]
        assert case["kind"] == "decision"
        assert case["expected_decision"] in {"match", "mint", "ambiguous"}
        assert case["expected_rule_id"]


def test_near_miss_case_is_the_documented_must_not_match_case():
    case = load_all_cases()["near_miss_different_dob"]
    referral_dob = case["referral"]["demographics"]["dob"]
    decoy = next(p for p in case["existing_persons"] if p["person_id"] == case["must_not_match_person_id"])
    assert decoy["demographics"]["last_name"] == case["referral"]["demographics"]["last_name"]
    assert decoy["demographics"]["dob"] != referral_dob
    assert case["expected_decision"] == "mint"


def test_suffix_casing_pairs_case_has_at_least_one_pair():
    case = load_all_cases()["suffix_casing_pairs"]
    assert case["kind"] == "normalization_pairs"
    assert len(case["pairs"]) >= 1
    for pair in case["pairs"]:
        assert pair["a"]["dob"] == pair["b"]["dob"]


def test_ambiguous_dob_case_names_the_dob_field():
    case = load_all_cases()["ambiguous_dob_format"]
    assert case["kind"] == "ambiguous_dob"
    assert case["expected_rejected_field"] == "dob"


def test_readme_documents_the_must_not_match_case_verbatim():
    readme = (FIXTURES_DIR / "README.md").read_text()
    assert "different DOB" in readme


@pytest.mark.parametrize(
    ("data", "expected_message_fragment"),
    [
        ({"case": "x", "description": "d"}, "missing required field 'kind'"),
        ({"kind": "decision", "description": "d"}, "missing or empty required field 'case'"),
        ({"kind": "decision", "case": "x"}, "missing or empty required field 'description'"),
        ({"kind": "mystery", "case": "x", "description": "d"}, "unknown kind"),
        (
            {"kind": "decision", "case": "x", "description": "d", "referral": "not-an-object"},
            "'referral' must be an object",
        ),
        (
            {
                "kind": "normalization_pairs",
                "case": "x",
                "description": "d",
                "pairs": [],
            },
            "'pairs' must be a non-empty list",
        ),
        (
            {
                "kind": "ambiguous_dob",
                "case": "x",
                "description": "d",
                "demographics": {"first_name": "a", "last_name": "b", "dob": "1990-01-01", "sex": "F"},
                "expected_rejected_field": "first_name",
            },
            "'expected_rejected_field' must be 'dob'",
        ),
    ],
)
def test_malformed_fixture_shapes_are_rejected(tmp_path: Path, data: dict[str, Any], expected_message_fragment: str):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(data))

    with pytest.raises(FixtureShapeError, match=expected_message_fragment):
        load_case(bad_file)
