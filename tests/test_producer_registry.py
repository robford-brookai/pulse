"""The producer-registry shape test (producer-registry spec, billing-source-boundary 1.1),
extended with the registry enforcement test (billing-source-boundary 3.1) and the legacy
inventory supersession test (billing-source-boundary 1.2).

Parses `docs/contracts/producer-registry.md`'s table and pins its shape: the exact column set,
the fixed `Direction`/`Status` vocabularies, at least one `excluded-by-design` row with a reason,
and the cpt-om row stating both directions and the amount-free citation — the same
parse-and-assert pattern as `tests/test_producer_ingress_policy.py`.

3.1 adds the enforcement half: a module-level mapping from each repo-resident ingress surface to
its required registry row, asserting both that the surface exists in the tree and that its row
exists in the table — so adding an ingress package without a registry row fails CI by name — plus
the `AGENTS.md` line requiring a change that introduces a new writer credential or ingress
package to add or update that row in the same change.

1.2 adds the legacy-inventory-points-forward scenario: the pre-connector-architecture surface
inventory names the registry as authoritative within its opening lines, so a reader who starts
there is redirected rather than misled.

Offline, no network, no credentials — reads only the committed docs.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "contracts" / "producer-registry.md"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
LEGACY_INVENTORY_PATH = REPO_ROOT / "packages" / "ocean" / "docs" / "pt-data-infra-acq-status.md"
LEGACY_INVENTORY_HEADER_LINES = 30

#: The task's pinned column set, in order.
EXPECTED_COLUMNS = (
    "System",
    "Direction",
    "Seam",
    "Credential / actor",
    "Grain",
    "Status",
    "Notes",
)

DIRECTION_VALUES = frozenset({"declares in", "consumes out", "both"})
STATUS_VALUES = frozenset({"shipped", "spec-only", "planned", "blocked", "excluded-by-design"})


def _split_row(line: str) -> list[str]:
    """A markdown table row `| a | b |` -> `["a", "b"]`, stripped, dropping the outer pipes."""
    stripped = line.strip()
    assert stripped.startswith("|") and stripped.endswith("|"), f"not a table row: {line!r}"
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def parse_registry_table(text: str) -> list[dict[str, str]]:
    """Parse the first markdown table in `text` into a list of {column: cell} row dicts.

    Finds the header row by its exact column set, skips the `---` separator, and reads every
    following pipe-delimited line as a data row until the table ends.
    """
    lines = text.splitlines()
    header_index = None
    for index, line in enumerate(lines):
        if line.strip().startswith("|") and _split_row(line) == list(EXPECTED_COLUMNS):
            header_index = index
            break
    assert header_index is not None, "no table header matching the expected column set was found"

    separator = lines[header_index + 1].strip()
    assert separator.startswith("|") and set(separator.replace("|", "").strip()) <= {"-", " ", ":"}, (
        f"expected a header separator row after the header, got: {separator!r}"
    )

    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = _split_row(line)
        assert len(cells) == len(EXPECTED_COLUMNS), (
            f"row has {len(cells)} cells, expected {len(EXPECTED_COLUMNS)}: {line!r}"
        )
        rows.append(dict(zip(EXPECTED_COLUMNS, cells, strict=True)))
    return rows


def _load_rows() -> list[dict[str, str]]:
    return parse_registry_table(DOC_PATH.read_text(encoding="utf-8"))


# --- The doc exists and its table has the exact shape ---------------------------------------


def test_the_registry_doc_exists() -> None:
    assert DOC_PATH.is_file()


def test_the_table_header_has_exactly_the_pinned_columns() -> None:
    rows = _load_rows()

    assert rows, "expected at least one data row in the producer registry table"
    for row in rows:
        assert set(row.keys()) == set(EXPECTED_COLUMNS)


# --- Scenario: A registry entry names its seam and its actor --------------------------------


def test_every_row_has_all_columns_populated() -> None:
    rows = _load_rows()

    for row in rows:
        for column in EXPECTED_COLUMNS:
            assert row[column], f"row {row['System']!r} has an empty {column!r} cell"


def test_every_direction_cell_is_in_the_fixed_vocabulary() -> None:
    rows = _load_rows()

    for row in rows:
        assert row["Direction"] in DIRECTION_VALUES, f"row {row['System']!r} has direction {row['Direction']!r}"


def test_every_status_cell_is_in_the_fixed_vocabulary() -> None:
    rows = _load_rows()

    for row in rows:
        assert row["Status"] in STATUS_VALUES, f"row {row['System']!r} has status {row['Status']!r}"


# --- Scenario: Deliberate exclusions are entries, not omissions -----------------------------


def test_at_least_one_row_is_excluded_by_design_with_a_reason_in_notes() -> None:
    rows = _load_rows()

    excluded = [row for row in rows if row["Status"] == "excluded-by-design"]
    assert excluded, "expected at least one excluded-by-design row"
    for row in excluded:
        assert row["Notes"], f"row {row['System']!r} is excluded-by-design but states no reason"


# --- Scenario: The revenue model's entry states both directions and the amount-free rule ----


def test_the_cpt_om_row_states_both_directions_and_the_amount_free_citation() -> None:
    rows = _load_rows()

    cpt_om_rows = [row for row in rows if "cpt-om" in row["System"].lower()]
    assert len(cpt_om_rows) == 1, f"expected exactly one cpt-om row, found {len(cpt_om_rows)}"
    row = cpt_om_rows[0]

    assert row["Direction"] == "both"
    assert "command api" in row["Seam"].lower()
    assert "billing-computation-boundary" in row["Notes"]


# --- Registry enforcement: repo-resident ingress surfaces (billing-source-boundary 3.1) -----


class IngressSurface(NamedTuple):
    """One repo-resident ingress surface: where it lives, and which registry row covers it."""

    path: Path
    system: str  # required substring (case-insensitive) of the registry row's `System` cell


#: Every repo-resident ingress surface, mapped to the filesystem path proving it exists in the
#: tree and the `System` substring its required registry row must contain. Adding an ingress
#: package without adding both sides of this mapping is the defect this test exists to catch —
#: the mapping is spelled out here, not derived, so a reviewer can see exactly what is covered.
REPO_INGRESS_SURFACES: dict[str, IngressSurface] = {
    "packages/consent-ingress": IngressSurface(
        path=REPO_ROOT / "packages" / "consent-ingress",
        system="customer.io consent ingress",
    ),
    "packages/verdict-relay": IngressSurface(
        path=REPO_ROOT / "packages" / "verdict-relay",
        system="warehouse verdict relay",
    ),
    "pulse_ledger.twenty (webhook)": IngressSurface(
        path=REPO_ROOT / "packages" / "pulse-ledger" / "src" / "pulse_ledger" / "twenty",
        system="twenty kanban webhook",
    ),
    "packages/identity": IngressSurface(
        path=REPO_ROOT / "packages" / "identity",
        system="identity-resolution",
    ),
}


def test_every_mapped_repo_resident_ingress_surface_exists_in_the_tree() -> None:
    for surface, entry in REPO_INGRESS_SURFACES.items():
        assert entry.path.is_dir(), (
            f"{surface!r} is mapped to a producer-registry row but {entry.path} does not exist "
            "in the tree — update the mapping if the surface moved or was removed"
        )


def test_every_mapped_repo_resident_ingress_surface_has_a_registry_row() -> None:
    rows = _load_rows()
    systems = [row["System"].lower() for row in rows]

    for surface, entry in REPO_INGRESS_SURFACES.items():
        assert any(entry.system in system for system in systems), (
            f"{surface!r} has no matching row in the producer registry "
            f"(expected a System containing {entry.system!r}) — a repo-resident ingress surface "
            "without a registry row is a defect, not a variant"
        )


# --- Scenario: the review-conventions line names the registry doc by name -------------------


def test_agents_md_requires_a_registry_row_for_a_new_writer_credential_or_ingress_package() -> None:
    text = AGENTS_PATH.read_text(encoding="utf-8")
    assert "producer-registry.md" in text


# --- Scenario: The legacy list points forward (billing-source-boundary 1.2) -----------------


def test_the_legacy_inventory_points_forward_to_the_registry() -> None:
    header = "\n".join(LEGACY_INVENTORY_PATH.read_text(encoding="utf-8").splitlines()[:LEGACY_INVENTORY_HEADER_LINES])

    assert "producer-registry.md" in header, (
        "the legacy inventory's first "
        f"{LEGACY_INVENTORY_HEADER_LINES} lines don't name the registry as the authoritative source"
    )
    assert "superseded" in header.lower(), (
        f"the legacy inventory's first {LEGACY_INVENTORY_HEADER_LINES} lines don't say it's superseded"
    )
