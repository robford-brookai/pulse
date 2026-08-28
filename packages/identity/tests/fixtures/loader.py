"""Loads and shape-validates the synthetic demographic fixtures in this directory.

These fixtures are pure data: no `identity.normalize` or `identity.matcher` import here, and
none is required — 2.2 only proves the fixture shape is sound. Later waves (3.1's matcher
tests, 5.1's determinism property test) import `load_all_cases`/`load_case` to drive the real
decision core against these same cases.

All demographics here are synthetic (invented names, invented DOBs) — no PHI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

FIXTURES_DIR = Path(__file__).resolve().parent

_DECISION_KINDS = frozenset({"match", "mint", "ambiguous"})
_REQUIRED_DEMOGRAPHIC_FIELDS = frozenset({"first_name", "last_name", "dob", "sex"})
_REQUIRED_IDENTIFIER_FIELDS = frozenset({"system", "value"})


class FixtureShapeError(ValueError):
    """Raised when a fixture file's JSON does not match its declared `kind`'s shape.

    Takes the source filename and a short defect description; builds the full message here
    so call sites stay to a single short argument (tryceratops TRY003).
    """

    def __init__(self, filename: str, detail: str) -> None:
        super().__init__(f"{filename}: {detail}")


def list_case_files() -> list[Path]:
    """Every fixture JSON file in this directory, sorted for deterministic iteration order."""
    return sorted(FIXTURES_DIR.glob("*.json"))


def load_case(path: Path) -> dict[str, Any]:
    """Load one fixture file and validate its shape against its declared `kind`.

    Raises FixtureShapeError naming the file and the defect if the shape is invalid.
    """
    data = cast("dict[str, Any]", json.loads(path.read_text()))
    _validate_shape(path.name, data)
    return data


def load_all_cases() -> dict[str, dict[str, Any]]:
    """Load and validate every fixture case, keyed by its `case` name."""
    cases: dict[str, dict[str, Any]] = {}
    for path in list_case_files():
        case = load_case(path)
        name = cast(str, case["case"])
        if name in cases:
            raise FixtureShapeError(path.name, f"duplicate case name {name!r}")
        cases[name] = case
    return cases


def _validate_shape(filename: str, data: dict[str, Any]) -> None:
    if "kind" not in data:
        raise FixtureShapeError(filename, "missing required field 'kind'")
    if "case" not in data or not isinstance(data["case"], str) or not data["case"]:
        raise FixtureShapeError(filename, "missing or empty required field 'case'")
    if "description" not in data or not isinstance(data["description"], str) or not data["description"]:
        raise FixtureShapeError(filename, "missing or empty required field 'description'")

    kind = data["kind"]
    if kind == "decision":
        _validate_decision_shape(filename, data)
    elif kind == "normalization_pairs":
        _validate_normalization_pairs_shape(filename, data)
    elif kind == "ambiguous_dob":
        _validate_ambiguous_dob_shape(filename, data)
    else:
        raise FixtureShapeError(filename, f"unknown kind {kind!r}")


def _validate_demographics(filename: str, label: str, demographics: object) -> None:
    if not isinstance(demographics, dict):
        raise FixtureShapeError(filename, f"{label} must be an object")
    demographics_dict = cast("dict[str, Any]", demographics)
    missing = _REQUIRED_DEMOGRAPHIC_FIELDS - demographics_dict.keys()
    if missing:
        raise FixtureShapeError(filename, f"{label} missing fields {sorted(missing)}")


def _validate_identifiers(filename: str, label: str, identifiers: object) -> None:
    if not isinstance(identifiers, list):
        raise FixtureShapeError(filename, f"{label} must be a list")
    for identifier in cast("list[Any]", identifiers):
        if not isinstance(identifier, dict) or _REQUIRED_IDENTIFIER_FIELDS - identifier.keys():
            raise FixtureShapeError(filename, f"{label} entry malformed: {identifier!r}")


def _validate_decision_shape(filename: str, data: dict[str, Any]) -> None:
    referral = data.get("referral")
    if not isinstance(referral, dict):
        raise FixtureShapeError(filename, "'referral' must be an object")
    referral_dict = cast("dict[str, Any]", referral)
    _validate_identifiers(filename, "referral.identifiers", referral_dict.get("identifiers"))
    _validate_demographics(filename, "referral.demographics", referral_dict.get("demographics"))

    existing_persons = data.get("existing_persons")
    if not isinstance(existing_persons, list):
        raise FixtureShapeError(filename, "'existing_persons' must be a list")
    for person in cast("list[Any]", existing_persons):
        if not isinstance(person, dict) or "person_id" not in person:
            raise FixtureShapeError(filename, "existing_persons entry missing 'person_id'")
        person_dict = cast("dict[str, Any]", person)
        _validate_identifiers(filename, "existing_persons[].identifiers", person_dict.get("identifiers"))
        _validate_demographics(filename, "existing_persons[].demographics", person_dict.get("demographics"))

    expected_decision = data.get("expected_decision")
    if expected_decision not in _DECISION_KINDS:
        raise FixtureShapeError(
            filename,
            f"'expected_decision' must be one of {sorted(_DECISION_KINDS)}, got {expected_decision!r}",
        )
    if "expected_rule_id" not in data or not data["expected_rule_id"]:
        raise FixtureShapeError(filename, "missing required field 'expected_rule_id'")


def _validate_normalization_pairs_shape(filename: str, data: dict[str, Any]) -> None:
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise FixtureShapeError(filename, "'pairs' must be a non-empty list")
    for pair in cast("list[Any]", pairs):
        if not isinstance(pair, dict) or "a" not in pair or "b" not in pair:
            raise FixtureShapeError(filename, f"pair missing 'a'/'b': {pair!r}")
        pair_dict = cast("dict[str, Any]", pair)
        _validate_demographics(filename, "pairs[].a", pair_dict["a"])
        _validate_demographics(filename, "pairs[].b", pair_dict["b"])


def _validate_ambiguous_dob_shape(filename: str, data: dict[str, Any]) -> None:
    _validate_demographics(filename, "demographics", data.get("demographics"))
    if data.get("expected_rejected_field") != "dob":
        raise FixtureShapeError(filename, "'expected_rejected_field' must be 'dob'")
