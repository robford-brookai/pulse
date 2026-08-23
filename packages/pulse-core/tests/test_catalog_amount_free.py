"""Catalog monetary deny-list guard (billing-source-boundary, delta requirement "PULSE computes no
monetary value", scenario "No catalog subject carries a monetary field").

PULSE records billing qualification, never a rate, amount, or code. This test loads the raw
catalog and asserts no subject name, state name, command field name, valueset name, transition-
reason (valueset code) key, or program field name contains a monetary term. It is a lexical
tripwire on the catalog's vocabulary, not a semantic review — see `docs/contracts/billing-
boundary.md` for the stated boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[3]
CATALOG_PATH = REPO_ROOT / "catalog" / "state_catalog.yaml"

# billing-source-boundary: terms that would smuggle a monetary value or a billing code into
# catalog state. Case-insensitive substring match against every identifier the catalog defines.
DENY_LIST: tuple[str, ...] = (
    "rate",
    "amount",
    "price",
    "revenue",
    "copay",
    "fee",
    "charge",
    "cost",
    "cpt",
    "hcpcs",
    "usd",
    "cents",
    "dollar",
)


def _collect_catalog_identifiers(catalog: dict[str, Any]) -> list[tuple[str, str]]:
    """Every field name, state name, and transition-reason key the catalog defines.

    Returns (subject_label, identifier) pairs so a failure names both where and what.
    """
    identifiers: list[tuple[str, str]] = []

    for subject_name, spec in catalog.get("subjects", {}).items():
        identifiers.append((subject_name, subject_name))
        for state_name in spec.get("transitions", {}):
            identifiers.append((subject_name, state_name))

    for command_name, spec in catalog.get("commands", {}).items():
        identifiers.append((command_name, command_name))
        for field_name in spec.get("fields", {}):
            identifiers.append((command_name, field_name))

    for valueset_name, spec in catalog.get("valuesets", {}).items():
        identifiers.append((valueset_name, valueset_name))
        for reason_key in spec.get("codes", {}):
            identifiers.append((valueset_name, reason_key))

    for program_name, spec in catalog.get("programs", {}).items():
        identifiers.append((program_name, program_name))
        for field_name in spec:
            identifiers.append((program_name, field_name))

    return identifiers


def _assert_amount_free(identifiers: list[tuple[str, str]]) -> None:
    """Raise naming the offending subject and field on the first deny-listed identifier."""
    for subject, identifier in identifiers:
        lowered = identifier.lower()
        for term in DENY_LIST:
            if term in lowered:
                msg = f"subject {subject!r} defines identifier {identifier!r}, which contains deny-listed term {term!r}"
                raise AssertionError(msg)


@pytest.fixture
def catalog_data() -> dict[str, Any]:
    with CATALOG_PATH.open() as fh:
        return yaml.safe_load(fh)


def test_guard_is_live_by_construction() -> None:
    """The guard must actually fail on a monetary field before we trust it to pass the real catalog."""
    synthetic = {
        "subjects": {
            "billing_episode": {
                "ownership": "ledger",
                "transitions": {"open": ["qualified"], "qualified": []},
            }
        },
        "commands": {
            "declare_verdict": {
                "fields": {"outcome": "verdict_outcome", "allowed_amount": "str"},
            }
        },
        "valuesets": {},
        "programs": {},
    }

    with pytest.raises(AssertionError, match="allowed_amount"):
        _assert_amount_free(_collect_catalog_identifiers(synthetic))


def test_catalog_defines_no_monetary_field(catalog_data: dict[str, Any]) -> None:
    identifiers = _collect_catalog_identifiers(catalog_data)

    assert identifiers, "collection found nothing to check — the catalog fixture is broken"
    _assert_amount_free(identifiers)
