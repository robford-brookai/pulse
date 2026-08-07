"""The D18 release renderer: deterministic, INSERT-only, version-stamped, tagged output.

Covers the `catalog-release` spec scenarios "A release renders insert-only rows for every
catalog surface" and "Catalog objects are tagged with the release version". Everything here is
offline and pure — the renderer touches no network and no warehouse; task 4.2 adds the guard and
the connection boundary.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pulse_core import catalog_release, catalog_snapshots
from pulse_core.catalog_breaking import BreakingFinding, ReleaseClassification
from pulse_core.catalog_gen import Catalog, load_catalog

REPO_ROOT = Path(__file__).parents[3]

NON_BREAKING = ReleaseClassification(findings=())
BREAKING = ReleaseClassification(
    findings=(
        BreakingFinding(
            kind="state_removed",
            names=("referral", "screened"),
            message="state referral.screened was removed — a consumer pinned to it has no landing place",
        ),
    )
)

SOURCE = catalog_release.ReleaseSource(
    git_commit="0" * 40,
    git_ref="refs/heads/main",
    snapshot_checksum="a" * 64,
    classification=NON_BREAKING,
)


@pytest.fixture
def catalog() -> Catalog:
    return load_catalog()


def tiny_catalog(**overrides: object) -> Catalog:
    """A minimal but complete catalog — one of every row kind, so row content is checkable."""
    data: dict[str, object] = {
        "catalog_version": "1.0.0",
        "subjects": {"referral": {"ownership": "ledger", "transitions": {"received": ["closed"], "closed": []}}},
        "commands": {},
        "valuesets": {"referral_closure_reason": {"description": "Why it closed.", "codes": {"deceased": "Dead."}}},
        "programs": {"pcm": {"display_name": "Principal Care Management", "exclusivity_group": "care_management"}},
    }
    data.update(overrides)
    return Catalog.model_validate(data)


def statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split("\n\n") if statement.strip()]


def split_literals(row: str) -> tuple[str, ...]:
    """Split one rendered VALUES tuple into its literals, respecting quoted commas."""
    literals, current, in_string = [], "", False
    index = 0
    while index < len(row):
        char = row[index]
        if in_string and char == "'" and row[index + 1 : index + 2] == "'":
            current += "''"
            index += 2
            continue
        if char == "'":
            in_string = not in_string
        if char == "," and not in_string:
            literals.append(current.strip())
            current = ""
        else:
            current += char
        index += 1
    literals.append(current.strip())
    return tuple(literals)


def insert_rows(script: str, table: str) -> list[tuple[str, ...]]:
    """Every VALUES tuple of the INSERT into `table`, as a tuple of raw SQL literals."""
    inserts = [s for s in statements(script) if re.match(rf"INSERT INTO \S+\.{table}\b", s)]
    assert len(inserts) == 1, f"expected exactly one INSERT into {table}, found {len(inserts)}"
    _, values_block = inserts[0].split("\nVALUES\n", maxsplit=1)
    tuples = re.findall(r"^ {4}\((.*)\),?;?$", values_block, flags=re.MULTILINE)
    return [split_literals(row) for row in tuples]


# --- Scenario: A release renders insert-only rows for every catalog surface -------------------


def test_every_catalog_surface_gets_an_insert(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    for table in catalog_release.ROW_TABLES:
        assert re.search(rf"^INSERT INTO \S+\.{table}\b", script, flags=re.MULTILINE), f"no INSERT into {table}"


def test_the_five_row_kinds_are_states_transitions_valuesets_programs_and_the_version() -> None:
    assert catalog_release.ROW_TABLES == ("STATES", "TRANSITIONS", "VALUESET_CODES", "PROGRAMS", "VERSIONS")


def test_every_rendered_row_is_stamped_with_the_catalog_version(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    for table in catalog_release.ROW_TABLES:
        rows = insert_rows(script, table)
        assert rows, f"{table} rendered no rows"
        for row in rows:
            assert row[0] == f"'{catalog.catalog_version}'", f"{table} row not stamped: {row}"


@pytest.mark.parametrize("forbidden", ["UPDATE", "DELETE", "MERGE", "TRUNCATE", "UPSERT", "DROP"])
def test_no_mutating_statement_is_ever_rendered(catalog: Catalog, forbidden: str) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    assert not re.search(rf"\b{forbidden}\b", script, flags=re.IGNORECASE)


def test_rendering_is_byte_identical_across_runs(catalog: Catalog) -> None:
    first = catalog_release.render_release_script(catalog, SOURCE)
    second = catalog_release.render_release_script(load_catalog(), SOURCE)
    assert first == second


def test_rendering_does_not_depend_on_yaml_key_order() -> None:
    ordered = tiny_catalog()
    shuffled = tiny_catalog(
        subjects={"referral": {"ownership": "ledger", "transitions": {"closed": [], "received": ["closed"]}}},
        programs={
            "pcm": {"display_name": "Principal Care Management", "exclusivity_group": "care_management"},
        },
    )
    assert catalog_release.render_release_script(ordered, SOURCE) == catalog_release.render_release_script(
        shuffled, SOURCE
    )


def test_ddl_creates_every_object_if_not_exists(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    assert re.search(r"^CREATE SCHEMA IF NOT EXISTS \S+;$", script, flags=re.MULTILINE)
    assert re.search(r"^CREATE TAG IF NOT EXISTS \S+", script, flags=re.MULTILINE)
    for table in catalog_release.ROW_TABLES:
        assert re.search(rf"^CREATE TABLE IF NOT EXISTS \S+\.{table} \($", script, flags=re.MULTILINE)
    creates = [s for s in statements(script) if s.startswith("CREATE")]
    assert all("IF NOT EXISTS" in statement for statement in creates)


def test_ddl_precedes_every_insert(catalog: Catalog) -> None:
    kinds = [
        statement.split(" ", 1)[0] for statement in statements(catalog_release.render_release_script(catalog, SOURCE))
    ]
    assert kinds.index("INSERT") > max(index for index, kind in enumerate(kinds) if kind == "CREATE")


def test_state_rows_carry_every_state_with_its_ownership(catalog: Catalog) -> None:
    rendered = {
        (row[1], row[2], row[3])
        for row in insert_rows(catalog_release.render_release_script(catalog, SOURCE), "STATES")
    }
    expected = {
        (f"'{subject}'", f"'{state}'", f"'{spec.ownership}'")
        for subject, spec in catalog.subjects.items()
        for state in spec.transitions
    }
    assert rendered == expected


def test_transition_rows_carry_every_legal_edge(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    rendered = {(row[1], row[2], row[3]) for row in insert_rows(script, "TRANSITIONS")}
    expected = {
        (f"'{subject}'", f"'{state}'", f"'{target}'")
        for subject, spec in catalog.subjects.items()
        for state, targets in spec.transitions.items()
        for target in targets
    }
    assert rendered == expected


def test_valueset_rows_carry_every_code(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    rendered = {(row[1], row[2]) for row in insert_rows(script, "VALUESET_CODES")}
    expected = {(f"'{valueset}'", f"'{code}'") for valueset, spec in catalog.valuesets.items() for code in spec.codes}
    assert rendered == expected


def test_program_rows_carry_config_with_unset_fields_as_null(catalog: Catalog) -> None:
    rows = {row[1]: row for row in insert_rows(catalog_release.render_release_script(catalog, SOURCE), "PROGRAMS")}
    assert set(rows) == {f"'{program}'" for program in catalog.programs}
    assert rows["'pcm'"][3] == "NULL", "pcm declares no entry_gate — it must render as NULL, not as an empty string"
    assert rows["'rpm'"][4] == "NULL", "rpm declares no exclusivity_group"


def test_rows_are_sorted_within_each_insert(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    for table in catalog_release.ROW_TABLES:
        rows = insert_rows(script, table)
        assert rows == sorted(rows), f"{table} rows are not deterministically ordered"


def test_string_literals_escape_embedded_quotes_and_backslashes() -> None:
    catalog = tiny_catalog(
        valuesets={
            "referral_closure_reason": {
                "description": "Why it closed.",
                "codes": {"deceased": "Patient's record \\ archived."},
            }
        }
    )
    script = catalog_release.render_release_script(catalog, SOURCE)
    assert "'Patient''s record \\\\ archived.'" in script


# --- The version row --------------------------------------------------------------------------


def test_the_version_row_carries_git_identity_checksum_and_classification(catalog: Catalog) -> None:
    (row,) = insert_rows(catalog_release.render_release_script(catalog, SOURCE), "VERSIONS")
    assert row[0] == f"'{catalog.catalog_version}'"
    assert row[1] == f"'{SOURCE.git_commit}'"
    assert row[2] == f"'{SOURCE.git_ref}'"
    assert row[3] == f"'{SOURCE.snapshot_checksum}'"
    assert row[4] == "FALSE"
    assert row[5] == "'[]'"


def test_a_breaking_release_records_its_findings_in_the_version_row(catalog: Catalog) -> None:
    source = catalog_release.ReleaseSource(
        git_commit=SOURCE.git_commit,
        git_ref=SOURCE.git_ref,
        snapshot_checksum=SOURCE.snapshot_checksum,
        classification=BREAKING,
    )
    (row,) = insert_rows(catalog_release.render_release_script(catalog, source), "VERSIONS")
    assert row[4] == "TRUE"
    assert "state_removed" in row[5]
    assert "referral" in row[5] and "screened" in row[5]


def test_the_version_row_is_the_only_row_kind_with_exactly_one_row(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    assert len(insert_rows(script, "VERSIONS")) == 1


# --- Scenario: Catalog objects are tagged with the release version ----------------------------


def test_the_release_creates_the_version_tag(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    config = catalog_release.ReleaseConfig()
    assert f"CREATE TAG IF NOT EXISTS {config.qualified(catalog_release.VERSION_TAG)}" in script


def test_every_catalog_object_is_tagged_with_the_released_version(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(catalog, SOURCE)
    config = catalog_release.ReleaseConfig()
    tag = config.qualified(catalog_release.VERSION_TAG)
    expected = {f"ALTER SCHEMA {config.schema_path} SET TAG {tag} = '{catalog.catalog_version}';"}
    expected |= {
        f"ALTER TABLE {config.qualified(table)} SET TAG {tag} = '{catalog.catalog_version}';"
        for table in catalog_release.ROW_TABLES
    }
    assert expected <= set(statements(script))


def test_tagging_follows_the_inserts(catalog: Catalog) -> None:
    kinds = [
        statement.split(" ", 1)[0] for statement in statements(catalog_release.render_release_script(catalog, SOURCE))
    ]
    assert min(index for index, kind in enumerate(kinds) if kind == "ALTER") > max(
        index for index, kind in enumerate(kinds) if kind == "INSERT"
    )


# --- Configuration: the database name is the open question --------------------------------------


def test_the_database_default_is_the_documented_placeholder() -> None:
    assert catalog_release.ReleaseConfig().database == catalog_release.PLACEHOLDER_DATABASE
    assert catalog_release.ReleaseConfig().schema_name == "CATALOG"


def test_the_database_is_configuration_and_qualifies_every_object(catalog: Catalog) -> None:
    script = catalog_release.render_release_script(
        catalog, SOURCE, config=catalog_release.ReleaseConfig(database="PULSE_PROD")
    )
    assert catalog_release.PLACEHOLDER_DATABASE not in script
    for line in script.splitlines():
        if line.startswith(("CREATE", "INSERT INTO", "ALTER")):
            assert "PULSE_PROD.CATALOG" in line, line


def test_an_unsafe_identifier_is_rejected_rather_than_interpolated() -> None:
    with pytest.raises(ValueError, match="database"):
        catalog_release.ReleaseConfig(database="PULSE; DELETE FROM X")


# --- The statement sequence is what task 4.2 executes -------------------------------------------


def test_render_release_returns_the_statements_the_script_joins(catalog: Catalog) -> None:
    rendered = catalog_release.render_release(catalog, SOURCE)
    assert isinstance(rendered, tuple)
    assert statements(catalog_release.render_release_script(catalog, SOURCE)) == [s.rstrip("\n") for s in rendered]
    assert all(statement.endswith(";") for statement in rendered)


def test_a_catalog_surface_with_no_rows_renders_no_insert() -> None:
    catalog = tiny_catalog(programs={})
    script = catalog_release.render_release_script(catalog, SOURCE)
    assert not re.search(r"^INSERT INTO \S+\.PROGRAMS\b", script, flags=re.MULTILINE)
    assert re.search(r"^CREATE TABLE IF NOT EXISTS \S+\.PROGRAMS \($", script, flags=re.MULTILINE)


# --- One checksum definition, shared with the manifest -------------------------------------------


def test_snapshot_checksum_is_the_manifest_checksum_for_the_released_version() -> None:
    """Design decision: manifest, version row, and guard share one checksum definition."""
    entries = {
        entry.version: entry.checksum
        for entry in catalog_snapshots.read_manifest(catalog_snapshots.RELEASES_DIR / catalog_snapshots.MANIFEST_NAME)
    }
    head_version = str(yaml.safe_load(catalog_snapshots.CATALOG_PATH.read_bytes())["catalog_version"])
    assert catalog_release.snapshot_checksum(head_version) == entries[head_version]


def test_snapshot_checksum_names_the_version_when_the_snapshot_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=re.escape("9.9.9")):
        catalog_release.snapshot_checksum("9.9.9", releases_dir=tmp_path)
