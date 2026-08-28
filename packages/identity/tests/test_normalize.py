"""Normalization rules v1: determinism, the DOB rejection contract, and the PHI boundary.

Every demographic value here is synthetic. The names are invented, the DOBs are arbitrary, and
none of it corresponds to a real person — per the repo PHI rules, fixtures are synthetic only.
"""

from __future__ import annotations

import datetime as dt
import re
from types import ModuleType

import pytest
from identity import normalize
from identity.normalize import Demographics, NormalizationError, composite_digest

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def demo(
    last_name: str = "Martinez",
    first_name: str = "Alex",
    dob: str | dt.date = "1990-03-04",
    sex: str = "F",
) -> Demographics:
    return Demographics(last_name=last_name, first_name=first_name, dob=dob, sex=sex)


# --- Determinism and the composite rules ------------------------------------------------------


def test_digest_matches_the_ledger_check_constraint():
    assert HEX64.match(composite_digest(demo()))


def test_same_input_yields_the_same_digest():
    assert composite_digest(demo()) == composite_digest(demo())


@pytest.mark.parametrize(
    ("variant", "canonical"),
    [
        # Casing.
        (demo(last_name="MARTINEZ", first_name="ALEX"), demo()),
        # Suffix, comma, and trailing period — the spec's worked pair.
        (demo(last_name="MARTINEZ, Jr."), demo()),
        (demo(last_name="Martinez Sr"), demo()),
        (demo(last_name="Martinez III"), demo()),
        (demo(last_name="martinez iv"), demo()),
        # Internal punctuation and whitespace.
        (demo(last_name="  Mar-tinez  "), demo()),
        (demo(last_name="Mar'tinez"), demo()),
        # Accents fold to their base letters.
        (demo(last_name="Martínez"), demo()),
        # Only the first initial of the given name survives.
        (demo(first_name="Alexandra"), demo()),
        (demo(first_name="a."), demo()),
        # Sex accepts long and short spellings of the same value.
        (demo(sex="female"), demo()),
        (demo(sex="F"), demo()),
        # DOB accepts several unambiguous spellings of the same day.
        (demo(dob="19900304"), demo()),
        (demo(dob="04 Mar 1990"), demo()),
        (demo(dob="March 4, 1990"), demo()),
        (demo(dob=dt.date(1990, 3, 4)), demo()),
        # `datetime` is a `date` subclass: its time part must not split one person in two.
        (demo(dob=dt.datetime(1990, 3, 4, 13, 45, tzinfo=dt.timezone.utc)), demo()),
    ],
)
def test_variants_normalize_to_the_same_digest(variant: Demographics, canonical: Demographics):
    assert composite_digest(variant) == composite_digest(canonical)


@pytest.mark.parametrize(
    "different",
    [
        demo(last_name="Martinsen"),
        demo(first_name="Blake"),
        demo(dob="1990-04-03"),
        demo(sex="M"),
    ],
)
def test_differing_demographics_yield_different_digests(different: Demographics):
    assert composite_digest(different) != composite_digest(demo())


def test_suffix_stripping_never_empties_a_name():
    """A surname that is nothing but a suffix token keeps its tokens (rules v1, R4 guard)."""
    assert composite_digest(demo(last_name="Sr")) != composite_digest(demo(last_name="Jr"))


# --- DOB rejection ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ambiguous",
    [
        "03/04/1990",
        "03-04-1990",
        "3.4.1990",
        "04/03/90",
        "1990/03/04",
        "yesterday",
        "",
        "4 Sept 1990",  # not a month spelling `calendar` knows — rejected, not guessed at
        "4 Brumaire 1990",
    ],
)
def test_ambiguous_dob_is_rejected_naming_the_field(ambiguous: str):
    with pytest.raises(NormalizationError) as excinfo:
        composite_digest(demo(dob=ambiguous))
    assert excinfo.value.field == "dob"
    assert excinfo.value.rule_id == "ambiguous_dob"
    assert "dob" in str(excinfo.value)


@pytest.mark.parametrize("impossible", ["1990-02-30", "19901301", "31 Feb 1990"])
def test_impossible_dob_is_rejected_as_invalid_not_guessed(impossible: str):
    with pytest.raises(NormalizationError) as excinfo:
        composite_digest(demo(dob=impossible))
    assert excinfo.value.field == "dob"
    assert excinfo.value.rule_id == "invalid_dob"


@pytest.mark.parametrize(
    ("field", "kwargs", "rule_id"),
    [
        ("last_name", {"last_name": "  "}, "missing_field"),
        ("last_name", {"last_name": "..."}, "missing_field"),
        ("first_name", {"first_name": ""}, "missing_field"),
        ("sex", {"sex": "yes"}, "unknown_sex"),
        ("sex", {"sex": ""}, "missing_field"),
    ],
)
def test_unusable_fields_are_rejected_by_name(field: str, kwargs: dict[str, str], rule_id: str):
    with pytest.raises(NormalizationError) as excinfo:
        composite_digest(demo(**kwargs))
    assert excinfo.value.field == field
    assert excinfo.value.rule_id == rule_id


# --- The PHI boundary -------------------------------------------------------------------------

SECRETS = ("Martinez", "martinez", "Alex", "1990-03-04", "19900304", "female")


def test_demographics_redact_in_repr_and_str():
    holder = demo()
    for rendered in (repr(holder), str(holder), f"{holder}", "{}".format(holder)):  # noqa: UP032
        assert "REDACTED" in rendered
        for secret in SECRETS:
            assert secret not in rendered


def test_demographics_redact_inside_a_container_repr():
    """`repr([holder])` and dict values go through `__repr__`, which is where a naive log leaks."""
    assert not any(s in repr([demo()]) for s in SECRETS)
    assert not any(s in repr({"subject": demo()}) for s in SECRETS)


@pytest.mark.parametrize(
    "bad",
    ["03/04/1990", "1990-02-30", "", "yesterday"],
)
def test_rejection_errors_never_echo_the_offending_value(bad: str):
    with pytest.raises(NormalizationError) as excinfo:
        composite_digest(demo(dob=bad))
    rendered = f"{excinfo.value!r} {excinfo.value}"
    assert bad not in rendered or bad == ""
    assert not any(s in rendered for s in SECRETS)


def test_the_readable_composite_has_no_public_exit():
    """Rules v1 / design decision 3: `composite_digest` is the only public exit of this module."""
    assert set(normalize.__all__) == {
        "RULES_VERSION",
        "Demographics",
        "NormalizationError",
        "composite_digest",
    }
    # Nothing *defined here* is public beyond `__all__` — a helper that returns the readable
    # composite cannot hide behind a public-but-unexported name.
    leaked = {
        name
        for name, obj in vars(normalize).items()
        if not name.startswith("_")
        and name not in normalize.__all__
        and not isinstance(obj, ModuleType)
        and getattr(obj, "__module__", None) == normalize.__name__
    }
    assert not leaked


def test_no_public_callable_returns_the_readable_composite():
    readable = normalize._composite(demo())  # pyright: ignore[reportPrivateUsage]
    assert "martinez" in readable
    for name in ("composite_digest",):
        assert getattr(normalize, name)(demo()) != readable


def test_the_digest_is_the_sha256_of_the_readable_composite():
    import hashlib

    readable = normalize._composite(demo())  # pyright: ignore[reportPrivateUsage]
    assert composite_digest(demo()) == hashlib.sha256(readable.encode("utf-8")).hexdigest()


def test_rules_are_versioned():
    assert normalize.RULES_VERSION == "v1"
