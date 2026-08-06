#!/usr/bin/env python
"""Demo 2 (partial) — the s14-identity slice of the s13+s14 receipt (DNA-849).

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints):
a runnable script under `scripts/demo/`, a runbook under `docs/runbooks/`, exits nonzero on any
failed assertion. Unlike Demo 1, this needs no LocalStack, no Postgres, no Docker at all — the
matcher (`identity.matcher.resolve`) is a pure function (design decision 1: no I/O, no ledger
writes), so this script drives it directly and stays in `task check`.

Drives `identity.matcher.resolve` against three of `packages/identity/tests/fixtures/`'s synthetic
decision cases plus one inline synthetic case, showing the matcher's four rule ids as printed
evidence:

1. Exact-identifier match (`exact_identifier_hit.json`) — `identifier_exact`.
2. Composite mint (`mint_unknown_everything.json`) — nothing matches at either tier, `composite_none`.
3. Two-candidate quarantine (`two_candidate_ambiguity.json`) — `composite_ambiguous`.
4. Identifier-conflict split — two referral identifiers held by two different existing persons,
   `identifier_conflict`. No fixture file names this case (checked: `tests/fixtures/*.json` has no
   `identifier_conflict` entry) — the referral and existing persons below are the same synthetic
   data `test_matcher.py`'s
   `test_identifiers_resolving_to_two_people_quarantine_rather_than_pick_one` already exercises,
   reproduced here rather than adding a fixture file this task does not own.

All demographics below are invented (no PHI). `identity.matcher.Referral`/`Person` redact under
`repr`, so nothing printed by this script — including a traceback, if one fired — carries a
demographic value; only rule ids, person ids, and candidate counts ever reach stdout, matching the
matcher's own evidence contract (design decision 2).

Usage:
    scripts/demo/demo2_identity_matcher.py
    scripts/demo/demo2_identity_matcher.py --help
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_TESTS_DIR = REPO_ROOT / "packages" / "identity" / "tests"
FIXTURES_DIR = IDENTITY_TESTS_DIR / "fixtures"

# `fixtures` is a test-local package (packages/identity/tests/fixtures/__init__.py) meant to be
# imported as `fixtures.loader` from any importer on its parent directory — the same sys.path
# convention packages/identity/tests/conftest.py itself uses.
sys.path.insert(0, str(IDENTITY_TESTS_DIR))

from fixtures.loader import load_case  # noqa: E402 - path insert above must run first
from identity.matcher import (  # noqa: E402
    Ambiguous,
    Decision,
    ExternalIdentifier,
    InMemoryLookup,
    Match,
    Person,
    Referral,
    resolve,
)
from identity.normalize import Demographics  # noqa: E402


class DemoAssertionError(AssertionError):
    """Raised by `_check` — caught once in `main`, same pattern as `demo1_ledger_core.py`."""


def _check(condition: object, message: str) -> None:
    if not condition:
        raise DemoAssertionError(message)


def _demographics(raw: dict[str, Any]) -> Demographics:
    return Demographics(last_name=raw["last_name"], first_name=raw["first_name"], dob=raw["dob"], sex=raw["sex"])


def _identifiers(raw: list[dict[str, str]]) -> tuple[ExternalIdentifier, ...]:
    return tuple(ExternalIdentifier(system=entry["system"], value=entry["value"]) for entry in raw)


def _referral_of(case: dict[str, Any]) -> Referral:
    raw = case["referral"]
    return Referral(demographics=_demographics(raw["demographics"]), identifiers=_identifiers(raw["identifiers"]))


def _lookup_of(case: dict[str, Any]) -> InMemoryLookup:
    return InMemoryLookup(
        Person(
            person_id=person["person_id"],
            demographics=_demographics(person["demographics"]),
            identifiers=_identifiers(person["identifiers"]),
        )
        for person in case["existing_persons"]
    )


def _print_decision(case_name: str, decision: Decision) -> None:
    payload: dict[str, Any] = {
        "case": case_name,
        "decision": type(decision).__name__.lower(),
        "rule_id": decision.evidence.rule_id,
        "matched_fields": list(decision.evidence.matched_fields),
        "candidate_count": decision.evidence.candidate_count,
    }
    if isinstance(decision, Match):
        payload["person_id"] = decision.person_id
    if isinstance(decision, Ambiguous):
        payload["candidates"] = list(decision.candidates)
    print(json.dumps(payload))


def step_fixture_case(case_name: str) -> Decision:
    """Load one fixture JSON's decision case and resolve it — steps 1-3."""
    case = load_case(FIXTURES_DIR / f"{case_name}.json")
    decision = resolve(_referral_of(case), _lookup_of(case))
    _print_decision(case_name, decision)
    _check(
        decision.evidence.rule_id == case["expected_rule_id"],
        f"{case_name}: expected rule_id {case['expected_rule_id']!r}, got {decision.evidence.rule_id!r}",
    )
    if isinstance(decision, Match):
        _check(
            decision.person_id == case.get("expected_person_id"),
            f"{case_name}: expected person_id {case.get('expected_person_id')!r}, got {decision.person_id!r}",
        )
    if isinstance(decision, Ambiguous):
        _check(
            list(decision.candidates) == case.get("expected_candidate_person_ids"),
            f"{case_name}: expected candidates {case.get('expected_candidate_person_ids')!r}, "
            f"got {list(decision.candidates)!r}",
        )
    return decision


def step_identifier_conflict() -> Decision:
    """Two referral identifiers, each held by a different existing person — no fixture file names
    this case (module docstring); reproduces `test_matcher.py`'s inline synthetic case verbatim."""
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
    _print_decision("identifier_conflict_split", decision)
    _check(isinstance(decision, Ambiguous), f"expected Ambiguous, got {type(decision).__name__}")
    _check(
        decision.evidence.rule_id == "identifier_conflict",
        f"expected rule_id identifier_conflict, got {decision.evidence.rule_id!r}",
    )
    _check(
        list(decision.candidates) == ["person-alpha", "person-beta"],
        f"expected candidates ['person-alpha', 'person-beta'], got {list(decision.candidates)!r}",
    )
    return decision


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="demo2_identity_matcher.py",
        description="Demo 2 (partial) — identity resolution slice (s14-identity, DNA-849).",
    )


def main(argv: Sequence[str] | None = None) -> int:
    build_arg_parser().parse_args(argv)

    print("=== Demo 2 (partial): identity resolution (s14-identity, DNA-849) ===")
    try:
        print("\n[1/4] exact-identifier match short-circuits the composite tier")
        step_fixture_case("exact_identifier_hit")

        print("\n[2/4] composite mint — unknown identifier, zero composite candidates")
        step_fixture_case("mint_unknown_everything")

        print("\n[3/4] two-candidate quarantine — composite tier finds two candidates")
        step_fixture_case("two_candidate_ambiguity")

        print("\n[4/4] identifier_conflict split — two identifiers, two different holders")
        step_identifier_conflict()
    except DemoAssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1

    print("\n=== Demo 2 (partial): all four identity assertions passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
