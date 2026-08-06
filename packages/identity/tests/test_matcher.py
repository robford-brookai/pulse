"""The two-tier deterministic matcher: exact identifier, then composite, decided by count alone.

Driven by the synthetic fixture set from task 2.2 (`tests/fixtures/`) — every demographic value
here is invented, no PHI. No live network (`conftest.py` blocks sockets).

The assertions that matter most are the ones about what the matcher *refuses* to do: it never
consults the composite tier once an identifier hits, it never auto-chooses between two candidates,
and it never lets a demographic value into evidence.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fixtures.loader import load_all_cases
from identity.matcher import (
    COMPOSITE_FIELDS,
    IDENTIFIER_FIELDS,
    RULE_COMPOSITE_AMBIGUOUS,
    RULE_COMPOSITE_NONE,
    RULE_COMPOSITE_UNIQUE,
    RULE_IDENTIFIER_CONFLICT,
    RULE_IDENTIFIER_EXACT,
    Ambiguous,
    CandidateLookup,
    Evidence,
    ExternalIdentifier,
    InMemoryLookup,
    Match,
    Mint,
    Person,
    Referral,
    resolve,
)
from identity.normalize import Demographics, NormalizationError

CASES = load_all_cases()

DECISION_CASES = (
    "exact_identifier_hit",
    "composite_unique_hit",
    "mint_unknown_everything",
    "two_candidate_ambiguity",
    "near_miss_different_dob",
)


def demographics(raw: dict[str, Any]) -> Demographics:
    return Demographics(
        last_name=raw["last_name"],
        first_name=raw["first_name"],
        dob=raw["dob"],
        sex=raw["sex"],
    )


def identifiers(raw: list[dict[str, str]]) -> tuple[ExternalIdentifier, ...]:
    return tuple(ExternalIdentifier(system=entry["system"], value=entry["value"]) for entry in raw)


def leakable_values(raw: dict[str, Any]) -> tuple[str, ...]:
    """Demographic values long enough for containment to mean something.

    `sex` is a single character and appears by chance in any hex digest, so asserting on it proves
    nothing either way. Name and DOB are what a leak would actually surface.
    """
    return tuple(str(value) for value in raw.values() if len(str(value)) > 2)


def referral_of(case: dict[str, Any]) -> Referral:
    raw = case["referral"]
    return Referral(demographics=demographics(raw["demographics"]), identifiers=identifiers(raw["identifiers"]))


def lookup_of(case: dict[str, Any]) -> InMemoryLookup:
    return InMemoryLookup(
        Person(
            person_id=person["person_id"],
            demographics=demographics(person["demographics"]),
            identifiers=identifiers(person["identifiers"]),
        )
        for person in case["existing_persons"]
    )


class RecordingLookup:
    """A `CandidateLookup` that counts calls — how the short-circuit is observed rather than assumed."""

    def __init__(self, inner: CandidateLookup) -> None:
        self._inner = inner
        self.identifier_calls: list[tuple[str, str]] = []
        self.candidate_calls: list[str] = []

    def lookup_identifier(self, system: str, value: str) -> str | None:
        self.identifier_calls.append((system, value))
        return self._inner.lookup_identifier(system, value)

    def find_candidates(self, match_key: str) -> tuple[str, ...]:
        self.candidate_calls.append(match_key)
        return tuple(self._inner.find_candidates(match_key))


# --- The identifier tier wins outright -------------------------------------------------------


def test_exact_identifier_hit_matches_the_identifier_holder():
    case = CASES["exact_identifier_hit"]
    decision = resolve(referral_of(case), lookup_of(case))
    assert decision == Match(
        person_id=case["expected_person_id"],
        evidence=Evidence(matched_fields=IDENTIFIER_FIELDS, rule_id=RULE_IDENTIFIER_EXACT, candidate_count=1),
    )


def test_exact_identifier_hit_never_consults_the_composite_tier():
    """The short-circuit is structural: with an identifier hit, no digest lookup happens at all."""
    case = CASES["exact_identifier_hit"]
    lookup = RecordingLookup(lookup_of(case))
    decision = resolve(referral_of(case), lookup)
    assert isinstance(decision, Match)
    assert lookup.candidate_calls == []


def test_identifier_hit_beats_a_composite_match_on_a_different_person():
    """Same demographics as an existing person, plus an identifier held by another: the identifier wins."""
    owner = Person(
        person_id="person-identifier-owner",
        demographics=Demographics(last_name="Okafor", first_name="Jordan", dob="1980-05-01", sex="M"),
        identifiers=(ExternalIdentifier("MRN-ACME", "SYN-7001"),),
    )
    composite_twin = Person(
        person_id="person-composite-twin",
        demographics=Demographics(last_name="Delacroix", first_name="Morgan", dob="1990-03-04", sex="F"),
    )
    referral = Referral(
        demographics=composite_twin.demographics,
        identifiers=(ExternalIdentifier("MRN-ACME", "SYN-7001"),),
    )
    decision = resolve(referral, InMemoryLookup([owner, composite_twin]))
    assert isinstance(decision, Match)
    assert decision.person_id == "person-identifier-owner"
    assert decision.evidence.rule_id == RULE_IDENTIFIER_EXACT


def test_one_known_identifier_among_unknown_ones_still_matches():
    owner = Person(
        person_id="person-owner",
        demographics=Demographics(last_name="Yamamoto", first_name="Toshiro", dob="2001-09-30", sex="M"),
        identifiers=(ExternalIdentifier("MRN-ACME", "SYN-7002"),),
    )
    referral = Referral(
        demographics=Demographics(last_name="Ashworth", first_name="Robin", dob="1970-01-05", sex="F"),
        identifiers=(
            ExternalIdentifier("MRN-OTHER", "SYN-UNKNOWN"),
            ExternalIdentifier("MRN-ACME", "SYN-7002"),
        ),
    )
    decision = resolve(referral, InMemoryLookup([owner]))
    assert isinstance(decision, Match)
    assert decision.person_id == "person-owner"


def test_identifiers_resolving_to_two_people_quarantine_rather_than_pick_one():
    """Two referral identifiers held by different persons is a conflict, never an auto-choice."""
    first = Person(
        person_id="person-alpha",
        demographics=Demographics(last_name="Okafor", first_name="Jordan", dob="1980-05-01", sex="M"),
        identifiers=(ExternalIdentifier("MRN-ACME", "SYN-7003"),),
    )
    second = Person(
        person_id="person-beta",
        demographics=Demographics(last_name="Rivera", first_name="Sam", dob="1975-06-19", sex="M"),
        identifiers=(ExternalIdentifier("MRN-OTHER", "SYN-7004"),),
    )
    referral = Referral(
        demographics=Demographics(last_name="Ashworth", first_name="Robin", dob="1970-01-05", sex="F"),
        identifiers=(ExternalIdentifier("MRN-OTHER", "SYN-7004"), ExternalIdentifier("MRN-ACME", "SYN-7003")),
    )
    decision = resolve(referral, InMemoryLookup([first, second]))
    assert decision == Ambiguous(
        candidates=("person-alpha", "person-beta"),
        evidence=Evidence(matched_fields=IDENTIFIER_FIELDS, rule_id=RULE_IDENTIFIER_CONFLICT, candidate_count=2),
    )


# --- The composite tier is a strict trichotomy -----------------------------------------------


def test_zero_candidates_mints():
    case = CASES["mint_unknown_everything"]
    decision = resolve(referral_of(case), lookup_of(case))
    assert decision == Mint(
        evidence=Evidence(matched_fields=COMPOSITE_FIELDS, rule_id=RULE_COMPOSITE_NONE, candidate_count=0)
    )


def test_one_candidate_matches():
    case = CASES["composite_unique_hit"]
    decision = resolve(referral_of(case), lookup_of(case))
    assert decision == Match(
        person_id=case["expected_person_id"],
        evidence=Evidence(matched_fields=COMPOSITE_FIELDS, rule_id=RULE_COMPOSITE_UNIQUE, candidate_count=1),
    )


def test_two_candidates_quarantine_and_carry_both():
    case = CASES["two_candidate_ambiguity"]
    decision = resolve(referral_of(case), lookup_of(case))
    assert decision == Ambiguous(
        candidates=tuple(case["expected_candidate_person_ids"]),
        evidence=Evidence(matched_fields=COMPOSITE_FIELDS, rule_id=RULE_COMPOSITE_AMBIGUOUS, candidate_count=2),
    )


def test_three_candidates_also_quarantine():
    """ ">1" is the rule, not "==2" — nothing about the third candidate changes the answer."""
    people = [
        Person(
            person_id=f"person-{index}",
            demographics=Demographics(last_name="Okafor", first_name=given, dob="1980-05-01", sex="M"),
        )
        for index, given in enumerate(("Jordan", "James", "Jules"))
    ]
    referral = Referral(demographics=Demographics(last_name="Okafor", first_name="Jordan", dob="1980-05-01", sex="M"))
    decision = resolve(referral, InMemoryLookup(people))
    assert isinstance(decision, Ambiguous)
    assert decision.candidates == ("person-0", "person-1", "person-2")
    assert decision.evidence.candidate_count == 3


# --- A near miss must not match ---------------------------------------------------------------


def test_same_name_different_dob_mints_and_never_names_the_decoy():
    case = CASES["near_miss_different_dob"]
    decision = resolve(referral_of(case), lookup_of(case))
    assert isinstance(decision, Mint)
    assert decision.evidence.candidate_count == 0
    assert case["must_not_match_person_id"] not in repr(decision)


def test_a_referral_with_no_identifiers_at_all_reaches_the_composite_tier():
    case = CASES["composite_unique_hit"]
    lookup = RecordingLookup(lookup_of(case))
    resolve(referral_of(case), lookup)
    assert lookup.identifier_calls == []
    assert len(lookup.candidate_calls) == 1


# --- Evidence ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", DECISION_CASES)
def test_every_decision_carries_fields_a_rule_id_and_a_candidate_count(name: str):
    case = CASES[name]
    decision = resolve(referral_of(case), lookup_of(case))
    evidence = decision.evidence
    assert evidence.matched_fields
    assert evidence.rule_id == case["expected_rule_id"]
    assert evidence.candidate_count >= 0
    assert {"match": Match, "mint": Mint, "ambiguous": Ambiguous}[case["expected_decision"]] is type(decision)


@pytest.mark.parametrize("name", DECISION_CASES)
def test_evidence_holds_field_names_never_demographic_values(name: str):
    """Evidence travels into command payloads; a value here would re-import the PHI the digest removed."""
    case = CASES[name]
    decision = resolve(referral_of(case), lookup_of(case))
    rendered = repr(decision)
    for value in leakable_values(case["referral"]["demographics"]):
        assert value not in rendered


def test_matched_fields_name_the_tier_that_decided():
    identifier_case = CASES["exact_identifier_hit"]
    composite_case = CASES["composite_unique_hit"]
    assert resolve(referral_of(identifier_case), lookup_of(identifier_case)).evidence.matched_fields == (
        "identifier_system",
        "identifier_value",
    )
    assert resolve(referral_of(composite_case), lookup_of(composite_case)).evidence.matched_fields == (
        "last_name",
        "dob",
        "sex",
        "first_initial",
    )


def test_candidate_count_equals_the_candidate_set_size_for_every_tier():
    case = CASES["two_candidate_ambiguity"]
    decision = resolve(referral_of(case), lookup_of(case))
    assert isinstance(decision, Ambiguous)
    assert decision.evidence.candidate_count == len(decision.candidates)


# --- Determinism ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", DECISION_CASES)
def test_resolution_is_re_run_identical(name: str):
    case = CASES[name]
    first = resolve(referral_of(case), lookup_of(case))
    second = resolve(referral_of(case), lookup_of(case))
    assert first == second


def test_identifier_order_does_not_change_the_decision():
    owner = Person(
        person_id="person-owner",
        demographics=Demographics(last_name="Yamamoto", first_name="Toshiro", dob="2001-09-30", sex="M"),
        identifiers=(ExternalIdentifier("MRN-ACME", "SYN-7005"),),
    )
    lookup = InMemoryLookup([owner])
    forward = (ExternalIdentifier("MRN-ACME", "SYN-7005"), ExternalIdentifier("MRN-OTHER", "SYN-UNKNOWN"))
    demo = Demographics(last_name="Ashworth", first_name="Robin", dob="1970-01-05", sex="F")
    assert resolve(Referral(demographics=demo, identifiers=forward), lookup) == resolve(
        Referral(demographics=demo, identifiers=tuple(reversed(forward))), lookup
    )


def test_person_insertion_order_does_not_change_an_ambiguous_decision():
    case = CASES["two_candidate_ambiguity"]
    forward = resolve(referral_of(case), lookup_of(case))
    reversed_case = {**case, "existing_persons": list(reversed(case["existing_persons"]))}
    assert resolve(referral_of(case), lookup_of(reversed_case)) == forward


def test_normalization_equivalents_resolve_identically():
    """Casing and a suffix are normalization concerns; the matcher must not see a difference."""
    owner = Person(
        person_id="person-owner",
        demographics=Demographics(last_name="Delacroix", first_name="Morgan", dob="1990-03-04", sex="F"),
    )
    lookup = InMemoryLookup([owner])
    plain = Referral(demographics=Demographics(last_name="Delacroix", first_name="Morgan", dob="1990-03-04", sex="F"))
    noisy = Referral(
        demographics=Demographics(last_name="DELACROIX Jr.", first_name="morgan", dob=dt.date(1990, 3, 4), sex="female")
    )
    assert resolve(noisy, lookup) == resolve(plain, lookup)


# --- The port and its in-memory adapter -------------------------------------------------------


def test_in_memory_lookup_satisfies_the_port():
    lookup: CandidateLookup = InMemoryLookup([])
    assert lookup.lookup_identifier("MRN-ACME", "SYN-0000") is None
    assert tuple(lookup.find_candidates("0" * 64)) == ()


def test_in_memory_lookup_returns_candidates_in_person_id_order():
    people = [
        Person(
            person_id=person_id,
            demographics=Demographics(last_name="Okafor", first_name="Jordan", dob="1980-05-01", sex="M"),
        )
        for person_id in ("person-zulu", "person-alpha", "person-mike")
    ]
    lookup = InMemoryLookup(people)
    referral = Referral(demographics=people[0].demographics)
    decision = resolve(referral, lookup)
    assert isinstance(decision, Ambiguous)
    assert decision.candidates == ("person-alpha", "person-mike", "person-zulu")


def test_in_memory_lookup_rejects_one_identifier_held_by_two_people():
    """`(system, value)` uniqueness is a store guarantee; the fake must not be laxer than the real one."""
    shared = ExternalIdentifier("MRN-ACME", "SYN-7006")
    people = [
        Person(
            person_id="person-one",
            demographics=Demographics(last_name="Okafor", first_name="Jordan", dob="1980-05-01", sex="M"),
            identifiers=(shared,),
        ),
        Person(
            person_id="person-two",
            demographics=Demographics(last_name="Rivera", first_name="Sam", dob="1975-06-19", sex="M"),
            identifiers=(shared,),
        ),
    ]
    with pytest.raises(ValueError, match="already held"):
        InMemoryLookup(people)


def test_in_memory_lookup_rejects_a_duplicate_person_id():
    demo = Demographics(last_name="Okafor", first_name="Jordan", dob="1980-05-01", sex="M")
    with pytest.raises(ValueError, match="duplicate"):
        InMemoryLookup([Person("person-one", demo), Person("person-one", demo)])


def test_lookup_receives_only_the_digest_never_the_readable_composite():
    case = CASES["composite_unique_hit"]
    lookup = RecordingLookup(lookup_of(case))
    resolve(referral_of(case), lookup)
    (match_key,) = lookup.candidate_calls
    assert len(match_key) == 64
    assert all(character in "0123456789abcdef" for character in match_key)
    for value in leakable_values(case["referral"]["demographics"]):
        assert value.casefold() not in match_key


# --- PHI containment --------------------------------------------------------------------------


def test_referral_and_person_reprs_redact():
    demo = Demographics(last_name="Delacroix", first_name="Morgan", dob="1990-03-04", sex="F")
    referral = Referral(demographics=demo, identifiers=(ExternalIdentifier("MRN-ACME", "SYN-7007"),))
    person = Person(person_id="person-one", demographics=demo, identifiers=referral.identifiers)
    for rendered in (repr(referral), str(referral), repr(person), str(person), f"{referral} {person}"):
        assert "Delacroix" not in rendered
        assert "Morgan" not in rendered
        assert "1990-03-04" not in rendered
        assert "SYN-7007" not in rendered


def test_a_container_repr_of_referrals_leaks_nothing():
    """A traceback rendering a list of referrals is the path decision 3 is guarding."""
    referrals = [
        Referral(demographics=Demographics(last_name="Delacroix", first_name="Morgan", dob="1990-03-04", sex="F"))
    ]
    assert "Delacroix" not in repr(referrals)


# --- Rejected input ---------------------------------------------------------------------------


def test_an_unnormalizable_dob_is_rejected_rather_than_matched():
    case = CASES["ambiguous_dob_format"]
    referral = Referral(demographics=demographics(case["demographics"]))
    with pytest.raises(NormalizationError) as raised:
        resolve(referral, InMemoryLookup([]))
    assert raised.value.field == "dob"
    assert case["demographics"]["dob"] not in str(raised.value)


def test_rule_ids_are_the_published_set():
    assert (
        RULE_IDENTIFIER_EXACT,
        RULE_IDENTIFIER_CONFLICT,
        RULE_COMPOSITE_UNIQUE,
        RULE_COMPOSITE_NONE,
        RULE_COMPOSITE_AMBIGUOUS,
    ) == ("identifier_exact", "identifier_conflict", "composite_unique", "composite_none", "composite_ambiguous")
