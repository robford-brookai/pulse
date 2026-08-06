"""`docs/matching.md` is executable documentation, not prose.

The normalization rules are a compatibility surface: a rule change changes composites, hence
digests, hence every `person_match_keys` row already registered (design — Risks). The published
table is therefore held to the package's actual output — every worked example in the doc is
re-derived here, so a rule edit that forgets the doc fails the suite instead of shipping a
document that no longer describes the code.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest
from identity import normalize
from identity.normalize import Demographics, NormalizationError, composite_digest

DOC = Path(__file__).resolve().parents[1] / "docs" / "matching.md"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _rows(heading: str) -> list[list[str]]:
    """Return the body cells of the pipe table that follows `heading` in the doc."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    after = lines[start + 1 :]
    first = next(i for i, line in enumerate(after) if line.startswith("|"))
    table = list(itertools.takewhile(lambda ln: ln.startswith("|"), after[first:]))
    assert table, f"no table under {heading!r}"
    body = [ln for ln in table if not set(ln) <= set("|-: ")][1:]
    return [[cell.strip().strip("`") for cell in ln.strip().strip("|").split("|")] for ln in body]


def _accepted() -> list[list[str]]:
    return _rows("## Worked examples")


def _rejected() -> list[list[str]]:
    return _rows("### Rejected inputs")


def test_the_doc_exists_and_declares_the_rules_version():
    text = DOC.read_text(encoding="utf-8")
    assert f"Rules version: **{normalize.RULES_VERSION}**" in text


def test_every_rule_id_the_module_can_raise_is_documented():
    text = DOC.read_text(encoding="utf-8")
    for rule_id in ("ambiguous_dob", "invalid_dob", "missing_field", "unknown_sex"):
        assert f"`{rule_id}`" in text


@pytest.mark.parametrize("row", _accepted(), ids=lambda row: row[0])
def test_each_worked_example_reproduces_the_packages_actual_output(row: list[str]):
    _label, last_name, first_name, dob, sex, composite, digest = row
    demographics = Demographics(last_name=last_name, first_name=first_name, dob=dob, sex=sex)
    assert normalize._composite(demographics) == composite  # pyright: ignore[reportPrivateUsage]
    assert composite_digest(demographics) == digest
    assert HEX64.match(digest)


@pytest.mark.parametrize("row", _rejected(), ids=lambda row: row[0])
def test_each_rejected_example_is_actually_rejected_with_the_documented_rule(row: list[str]):
    _label, last_name, first_name, dob, sex, field, rule_id = row
    demographics = Demographics(last_name=last_name, first_name=first_name, dob=dob, sex=sex)
    with pytest.raises(NormalizationError) as excinfo:
        composite_digest(demographics)
    assert (excinfo.value.field, excinfo.value.rule_id) == (field, rule_id)


def test_the_documented_variants_collapse_onto_the_documented_canonical_example():
    """The doc's whole claim: a reviewer can tell which rows are the same person."""
    by_digest: dict[str, set[str]] = {}
    for row in _accepted():
        by_digest.setdefault(row[6], set()).add(row[0])
    assert any(len(labels) > 1 for labels in by_digest.values()), (
        "the worked examples must include at least one variant pair that collapses"
    )
