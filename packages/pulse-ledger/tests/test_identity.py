"""The identity registry — task 4.1's two lookups and the uniqueness that makes them safe.

The spec scenarios: an exact `(system, value)` lookup returns exactly one person, and attaching an
identifier already held by someone else is rejected with the holder named. Around them: the
composite fallback returns the candidate set the matcher decides on, and the ledger refuses to store
a readable composite at all — the digest check is what keeps demographics out of this table.

Values here are synthetic MRNs and opaque digests. No demographics appear in this file, which is the
same rule the code enforces.
"""

from __future__ import annotations

import hashlib

import psycopg
import pytest
from pulse_ledger.identity import (
    BlankFieldError,
    IdentifierConflictError,
    MalformedMatchKeyError,
    attach_identifier,
    find_candidates,
    identifiers_for_person,
    lookup_identifier,
    register_match_key,
)

SERVICE_ROLE = "pulse_ledger_service"

MRN_SYSTEM = "https://brook.ai/id/mrn/synthetic-clinic"
NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"

PERSON_A = "tide-000000000000000a"
PERSON_B = "tide-000000000000000b"


def _digest(seed: str) -> str:
    """Stand-in for the matcher's normalized-composite digest — a digest of a synthetic seed."""
    return hashlib.sha256(seed.encode()).hexdigest()


def _attach(conn: psycopg.Connection, system: str, value: str, person_key: str) -> object:
    return attach_identifier(
        conn,
        system=system,
        value=value,
        person_key=person_key,
        actor_type="system",
        actor_id="identity-resolver",
    )


# --- exact identifier match --------------------------------------------------------------------


def test_an_exact_identifier_lookup_returns_the_one_person_holding_it(ledger_db: psycopg.Connection) -> None:
    _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)
    _attach(ledger_db, MRN_SYSTEM, "MRN-002", PERSON_B)

    found = lookup_identifier(ledger_db, system=MRN_SYSTEM, value="MRN-001")

    assert found is not None
    assert found.person_key == PERSON_A
    assert found.actor_id == "identity-resolver"


def test_a_lookup_the_ledger_holds_no_binding_for_returns_none(ledger_db: psycopg.Connection) -> None:
    _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)

    assert lookup_identifier(ledger_db, system=MRN_SYSTEM, value="MRN-999") is None
    # The system is half the key: the same value under another system is a different identifier.
    assert lookup_identifier(ledger_db, system=NPI_SYSTEM, value="MRN-001") is None


def test_identifiers_for_person_returns_every_binding_in_key_order(ledger_db: psycopg.Connection) -> None:
    _attach(ledger_db, NPI_SYSTEM, "1234567893", PERSON_A)
    _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)
    _attach(ledger_db, MRN_SYSTEM, "MRN-002", PERSON_B)

    held = identifiers_for_person(ledger_db, PERSON_A)

    assert [(binding.system, binding.value) for binding in held] == [
        (NPI_SYSTEM, "1234567893"),
        (MRN_SYSTEM, "MRN-001"),
    ]


# --- uniqueness at resolution time ------------------------------------------------------------


def test_attaching_a_duplicate_identifier_is_rejected_and_names_the_holder(ledger_db: psycopg.Connection) -> None:
    _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)

    with pytest.raises(IdentifierConflictError) as raised:
        _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_B)

    assert raised.value.holder == PERSON_A
    assert raised.value.requested == PERSON_B
    assert PERSON_A in str(raised.value)
    # The rejected attach wrote nothing: the binding still resolves to A.
    still = lookup_identifier(ledger_db, system=MRN_SYSTEM, value="MRN-001")
    assert still is not None and still.person_key == PERSON_A


def test_reattaching_the_same_identifier_to_the_same_person_is_a_replay(ledger_db: psycopg.Connection) -> None:
    first = _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)

    again = _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)

    assert again == first
    rows = ledger_db.execute("SELECT count(*) FROM ledger.external_identifiers").fetchone()
    assert rows == (1,)


def test_the_store_enforces_uniqueness_even_against_a_direct_insert(ledger_db: psycopg.Connection) -> None:
    """The rule is the primary key, not a check the resolver performs and could skip."""
    _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)

    with pytest.raises(psycopg.errors.UniqueViolation):
        ledger_db.execute(
            "INSERT INTO ledger.external_identifiers (system, value, person_key, actor_type, actor_id)"
            " VALUES (%s, %s, %s, 'system', 'rogue-writer')",
            (MRN_SYSTEM, "MRN-001", PERSON_B),
        )


def test_a_blank_identifier_field_is_refused(ledger_db: psycopg.Connection) -> None:
    for system, value, person_key in ((" ", "MRN-001", PERSON_A), (MRN_SYSTEM, "", PERSON_A), (MRN_SYSTEM, "M", " ")):
        with pytest.raises(BlankFieldError):
            _attach(ledger_db, system, value, person_key)


def test_a_binding_cannot_be_moved_by_the_service_role(ledger_db: psycopg.Connection) -> None:
    """Rebinding an MRN from one patient to another is a `merge_person` declaration, not an UPDATE."""
    _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)

    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            ledger_db.execute("UPDATE ledger.external_identifiers SET person_key = %s", (PERSON_B,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            ledger_db.execute("DELETE FROM ledger.external_identifiers")
    finally:
        ledger_db.execute("RESET ROLE")


# --- candidate retrieval by the normalized composite ------------------------------------------


def test_candidate_retrieval_returns_every_person_under_the_composite(ledger_db: psycopg.Connection) -> None:
    shared = _digest("synthetic-composite-1")
    register_match_key(ledger_db, person_key=PERSON_B, match_key=shared)
    register_match_key(ledger_db, person_key=PERSON_A, match_key=shared)
    register_match_key(ledger_db, person_key="tide-000000000000000c", match_key=_digest("synthetic-composite-2"))

    assert find_candidates(ledger_db, shared) == [PERSON_A, PERSON_B]


def test_no_candidates_is_an_empty_set_not_an_error(ledger_db: psycopg.Connection) -> None:
    assert find_candidates(ledger_db, _digest("nobody")) == []


def test_a_person_may_carry_several_composites(ledger_db: psycopg.Connection) -> None:
    """A name change mints a new digest; the old one keeps matching records that still use it."""
    before, after = _digest("synthetic-before"), _digest("synthetic-after")
    register_match_key(ledger_db, person_key=PERSON_A, match_key=before)
    register_match_key(ledger_db, person_key=PERSON_A, match_key=after)

    assert find_candidates(ledger_db, before) == [PERSON_A]
    assert find_candidates(ledger_db, after) == [PERSON_A]


def test_registering_the_same_composite_twice_is_idempotent(ledger_db: psycopg.Connection) -> None:
    key = _digest("synthetic-composite-1")
    register_match_key(ledger_db, person_key=PERSON_A, match_key=key)
    register_match_key(ledger_db, person_key=PERSON_A, match_key=key)

    assert ledger_db.execute("SELECT count(*) FROM ledger.person_match_keys").fetchone() == (1,)


def test_a_readable_composite_cannot_be_stored_or_looked_up(ledger_db: psycopg.Connection) -> None:
    """The composite is PHI in readable form, so only its digest is accepted — on both paths."""
    with pytest.raises(MalformedMatchKeyError):
        register_match_key(ledger_db, person_key=PERSON_A, match_key="doe|1970-01-01|f|j")
    with pytest.raises(MalformedMatchKeyError):
        find_candidates(ledger_db, "doe|1970-01-01|f|j")
    # Uppercase hex is not the digest form either — one representation, so one row per composite.
    with pytest.raises(MalformedMatchKeyError):
        register_match_key(ledger_db, person_key=PERSON_A, match_key=_digest("x").upper())


def test_the_store_refuses_a_non_digest_match_key_too(ledger_db: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        ledger_db.execute(
            "INSERT INTO ledger.person_match_keys (person_key, match_key) VALUES (%s, %s)",
            (PERSON_A, "doe|1970-01-01|f|j"),
        )


def test_the_service_role_can_attach_and_resolve(ledger_db: psycopg.Connection) -> None:
    ledger_db.execute(f"SET ROLE {SERVICE_ROLE}")
    try:
        _attach(ledger_db, MRN_SYSTEM, "MRN-001", PERSON_A)
        register_match_key(ledger_db, person_key=PERSON_A, match_key=_digest("synthetic-composite-1"))

        found = lookup_identifier(ledger_db, system=MRN_SYSTEM, value="MRN-001")
        assert found is not None and found.person_key == PERSON_A
        assert find_candidates(ledger_db, _digest("synthetic-composite-1")) == [PERSON_A]
    finally:
        ledger_db.execute("RESET ROLE")
