"""The billing-computation-boundary contract page test (billing-source-boundary 1.3).

Pins the published boundary statement in `docs/contracts/billing-boundary.md`: the page exists,
names the verdict-shaped record it keeps (`qualification`, `rule_version`), names the D6 terminal
(`reported`), links the registry row that carries the seam (`producer-registry.md`), and carries
no dollar-amount literal of its own — a boundary page that quotes a rate has already crossed the
line it states. Also asserts `mkdocs.yml` nav reaches both contracts pages this change adds, so
the contract is navigable rather than merely committed.

Delta scenario covered: billing-computation-boundary / "The contract answers the question
directly".

Offline, no network, no credentials — reads only the committed docs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "contracts" / "billing-boundary.md"
MKDOCS_PATH = REPO_ROOT / "mkdocs.yml"

#: Strings the task pins as present. Each is load-bearing, not decorative: the record PULSE keeps
#: (`qualification`), its provenance field (`rule_version`), the D6 terminal state (`reported`),
#: and the registry page that names the external revenue model's seam.
REQUIRED_STRINGS = (
    "reported",
    "rule_version",
    "producer-registry.md",
    "qualification",
)

#: A dollar-amount literal — `$5`, `$0.00`, `$1,200`. The boundary page carries no rates.
DOLLAR_AMOUNT = re.compile(r"\$[0-9]")

#: The two contracts pages this change adds to the nav (paths as mkdocs writes them, relative to
#: `docs/`).
NAV_PAGES = ("contracts/producer-registry.md", "contracts/billing-boundary.md")


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_boundary_page_exists() -> None:
    """The page is where an integrator reading `docs/contracts/` will look."""
    assert DOC_PATH.exists(), f"{DOC_PATH.relative_to(REPO_ROOT)} is missing"
    assert _doc_text().strip(), f"{DOC_PATH.relative_to(REPO_ROOT)} is empty"


def test_boundary_page_states_the_verdict_shaped_contract() -> None:
    """Every pinned string is present, each named in the failure message."""
    text = _doc_text()
    missing = [needle for needle in REQUIRED_STRINGS if needle not in text]
    assert not missing, (
        f"docs/contracts/billing-boundary.md must state {missing} — "
        "the boundary is qualification recorded with its rule version, terminating at "
        "`reported`, with the external revenue model named via the producer registry"
    )


def test_boundary_page_carries_no_dollar_amount() -> None:
    """The page states that PULSE prices nothing; quoting a rate would contradict it."""
    hits = DOLLAR_AMOUNT.findall(_doc_text())
    assert not hits, (
        "docs/contracts/billing-boundary.md contains a dollar-amount literal "
        f"({hits!r}) — rates belong to the registered external revenue model, "
        "not to the page that says PULSE holds none"
    )


def test_dollar_amount_guard_is_live() -> None:
    """Self-check: the regex the page passes actually catches an amount."""
    assert DOLLAR_AMOUNT.search("the allowed amount is $123.45")
    assert not DOLLAR_AMOUNT.search("no rate, no amount, no fee schedule")


def test_mkdocs_nav_reaches_both_new_contracts_pages() -> None:
    """A contract nobody can navigate to is not published (`mkdocs build -s` builds the nav)."""
    nav = yaml.safe_load(MKDOCS_PATH.read_text(encoding="utf-8")).get("nav", [])
    nav_text = json.dumps(nav)
    missing = [page for page in NAV_PAGES if page not in nav_text]
    assert not missing, f"mkdocs.yml nav must include {missing}"
