"""The D18 release renderer: one catalog version as deterministic, INSERT-only Snowflake SQL.

Released catalog versions live in Snowflake as immutable, tagged rows (D18 / ADR-0004,
runtime-readiness §4): edits stay in git, merge to main triggers the release job, and no hand
edit ever changes a released row. This module is the *build* half of that job — a pure function
from a loaded `Catalog` plus its release identity to a statement sequence. Nothing here opens a
connection, reads a credential, or touches the network. The *apply* half lives here too:
`apply_release` executes what the renderer renders through the thin `ReleaseConnection`
boundary, behind the immutability guard — an existing version row with a matching checksum makes
the run a successful no-op, a differing checksum hard-fails before any write, and a fresh
version applies inside one transaction. The snowflake driver is an adapter the deploy entrypoint
supplies (task 4.3); nothing in this module imports it, so tests fake the boundary.

What it renders, in order:

1. `CREATE ... IF NOT EXISTS` DDL — the `catalog` schema, the five tables, and the
   `CATALOG_VERSION` tag object. A release must be able to run against an empty account and
   against an account twenty releases deep, unchanged.
2. INSERT-only rows for the five catalog surfaces — states, transitions, ValueSet codes,
   programs, and the one version row carrying release metadata (version, git identity, sha256 of
   the frozen snapshot, breaking classification). Every row's first column is the immutable
   `catalog_version`.
3. `ALTER ... SET TAG` — the schema and every table tagged with the released version, so object
   tagging and access history answer "who read or changed catalog state" (§4.2).

Two properties the tests pin, because consumers depend on them:

- **INSERT-only.** No UPDATE, DELETE, MERGE, or TRUNCATE is renderable. An upsert is exactly the
  "hand edit by job bug" D18 forbids; the guard plus insert-only makes rewriting released rows
  structurally unavailable rather than merely discouraged.
- **Deterministic.** The same catalog version renders byte-identical output — every collection
  is sorted before it reaches a line, so a re-release can be byte-compared rather than trusted.

The database name is configuration with a placeholder default (`ReleaseConfig.database`): which
account database homes the `catalog` schema is the change's one open question, pinned by the
first credentialed deploy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pulse_core.catalog_breaking import ReleaseClassification
from pulse_core.catalog_gen import Catalog
from pulse_core.catalog_snapshots import RELEASES_DIR, checksum_bytes

# Placeholder until the first credentialed deploy pins the account database (design open
# question). It is deliberately not a plausible real name: a release that reaches Snowflake
# under this database was misconfigured, and the name says so.
PLACEHOLDER_DATABASE = "PULSE_CATALOG_PLACEHOLDER"

CATALOG_SCHEMA = "CATALOG"
VERSION_TAG = "CATALOG_VERSION"

# The five row kinds D18 names, in the order a release writes them: the four catalog surfaces,
# then the version row that declares the release complete.
ROW_TABLES = ("STATES", "TRANSITIONS", "VALUESET_CODES", "PROGRAMS", "VERSIONS")

# Unquoted Snowflake identifiers: the renderer interpolates these into SQL, so anything that is
# not one is rejected at construction rather than escaped.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

_COLUMNS: dict[str, tuple[str, ...]] = {
    "STATES": ("CATALOG_VERSION", "SUBJECT_TYPE", "STATE", "OWNERSHIP"),
    "TRANSITIONS": ("CATALOG_VERSION", "SUBJECT_TYPE", "FROM_STATE", "TO_STATE"),
    "VALUESET_CODES": ("CATALOG_VERSION", "VALUESET", "CODE", "DISPLAY", "VALUESET_DESCRIPTION"),
    "PROGRAMS": ("CATALOG_VERSION", "PROGRAM", "DISPLAY_NAME", "ENTRY_GATE", "EXCLUSIVITY_GROUP"),
    "VERSIONS": (
        "CATALOG_VERSION",
        "GIT_COMMIT",
        "GIT_REF",
        "CONTENT_CHECKSUM",
        "BREAKING",
        "BREAKING_FINDINGS",
    ),
}

# `RELEASED_AT` is a column default rather than a rendered value: the rendered release must be
# byte-identical across runs, and a timestamp in the text would defeat that.
_TABLE_DDL: dict[str, tuple[str, ...]] = {
    "STATES": (
        "CATALOG_VERSION VARCHAR NOT NULL",
        "SUBJECT_TYPE VARCHAR NOT NULL",
        "STATE VARCHAR NOT NULL",
        "OWNERSHIP VARCHAR NOT NULL",
        "RELEASED_AT TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()",
    ),
    "TRANSITIONS": (
        "CATALOG_VERSION VARCHAR NOT NULL",
        "SUBJECT_TYPE VARCHAR NOT NULL",
        "FROM_STATE VARCHAR NOT NULL",
        "TO_STATE VARCHAR NOT NULL",
        "RELEASED_AT TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()",
    ),
    "VALUESET_CODES": (
        "CATALOG_VERSION VARCHAR NOT NULL",
        "VALUESET VARCHAR NOT NULL",
        "CODE VARCHAR NOT NULL",
        "DISPLAY VARCHAR NOT NULL",
        "VALUESET_DESCRIPTION VARCHAR NOT NULL",
        "RELEASED_AT TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()",
    ),
    "PROGRAMS": (
        "CATALOG_VERSION VARCHAR NOT NULL",
        "PROGRAM VARCHAR NOT NULL",
        "DISPLAY_NAME VARCHAR NOT NULL",
        "ENTRY_GATE VARCHAR",
        "EXCLUSIVITY_GROUP VARCHAR",
        "RELEASED_AT TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()",
    ),
    "VERSIONS": (
        "CATALOG_VERSION VARCHAR NOT NULL",
        "GIT_COMMIT VARCHAR NOT NULL",
        "GIT_REF VARCHAR NOT NULL",
        # The sha256 of the frozen snapshot file — the one checksum definition the manifest, this
        # row, and the 4.2 guard all share (`catalog_snapshots.checksum_bytes`).
        "CONTENT_CHECKSUM VARCHAR NOT NULL",
        "BREAKING BOOLEAN NOT NULL",
        # JSON text, not VARIANT: `INSERT ... VALUES` takes literals only, and a version row that
        # needs `PARSE_JSON` would need an `INSERT ... SELECT` the guard then has to special-case.
        "BREAKING_FINDINGS VARCHAR NOT NULL",
        "RELEASED_AT TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()",
    ),
}

Row = tuple[str | bool | None, ...]


@dataclass(frozen=True)
class ReleaseConfig:
    """Where the `catalog` schema lives. The database is the design's one open question."""

    database: str = PLACEHOLDER_DATABASE
    schema_name: str = CATALOG_SCHEMA

    def __post_init__(self) -> None:
        for label, value in (("database", self.database), ("schema_name", self.schema_name)):
            if not _IDENTIFIER.fullmatch(value):
                msg = f"{label} {value!r} is not a bare Snowflake identifier"
                raise ValueError(msg)

    @property
    def schema_path(self) -> str:
        return f"{self.database}.{self.schema_name}"

    def qualified(self, name: str) -> str:
        """Fully qualify an object in the catalog schema — tables and the version tag alike."""
        return f"{self.schema_path}.{name}"


@dataclass(frozen=True)
class ReleaseSource:
    """The release identity that is not in the catalog file: git provenance and the checksum.

    `snapshot_checksum` is the sha256 of `catalog/releases/v<version>.yaml`, and
    `classification` is what `catalog_breaking.classify_release` returned for this version
    against its predecessor. Both are inputs rather than lookups so the renderer stays pure.
    """

    git_commit: str
    git_ref: str
    snapshot_checksum: str
    classification: ReleaseClassification = field(default_factory=lambda: ReleaseClassification(findings=()))


def snapshot_checksum(version: str, releases_dir: Path = RELEASES_DIR) -> str:
    """The released version's content checksum, by the one shared definition."""
    snapshot_path = releases_dir / f"v{version}.yaml"
    if not snapshot_path.is_file():
        msg = f"no frozen snapshot for catalog version {version}: {snapshot_path}"
        raise FileNotFoundError(msg)
    return checksum_bytes(snapshot_path.read_bytes())


def _literal(value: str | bool | None) -> str:
    """One SQL literal. Strings are single-quoted with quote and backslash doubled."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _state_rows(catalog: Catalog) -> list[Row]:
    return sorted(
        (catalog.catalog_version, subject, state, spec.ownership)
        for subject, spec in catalog.subjects.items()
        for state in spec.transitions
    )


def _transition_rows(catalog: Catalog) -> list[Row]:
    return sorted(
        (catalog.catalog_version, subject, state, target)
        for subject, spec in catalog.subjects.items()
        for state, targets in spec.transitions.items()
        for target in targets
    )


def _valueset_rows(catalog: Catalog) -> list[Row]:
    return sorted(
        (catalog.catalog_version, valueset, code, display, spec.description)
        for valueset, spec in catalog.valuesets.items()
        for code, display in spec.codes.items()
    )


def _program_rows(catalog: Catalog) -> list[Row]:
    return sorted(
        (catalog.catalog_version, program, spec.display_name, spec.entry_gate, spec.exclusivity_group)
        for program, spec in catalog.programs.items()
    )


def _findings_json(classification: ReleaseClassification) -> str:
    """The breaking findings as deterministic JSON — already sorted by `classify_release`."""
    return json.dumps(
        [
            {"kind": finding.kind, "names": list(finding.names), "message": finding.message}
            for finding in classification.findings
        ],
        separators=(",", ":"),
    )


def _version_rows(catalog: Catalog, source: ReleaseSource) -> list[Row]:
    return [
        (
            catalog.catalog_version,
            source.git_commit,
            source.git_ref,
            source.snapshot_checksum,
            source.classification.breaking,
            _findings_json(source.classification),
        )
    ]


def _rows(catalog: Catalog, source: ReleaseSource) -> dict[str, list[Row]]:
    return {
        "STATES": _state_rows(catalog),
        "TRANSITIONS": _transition_rows(catalog),
        "VALUESET_CODES": _valueset_rows(catalog),
        "PROGRAMS": _program_rows(catalog),
        "VERSIONS": _version_rows(catalog, source),
    }


def _render_ddl(config: ReleaseConfig) -> list[str]:
    statements = [
        f"CREATE SCHEMA IF NOT EXISTS {config.schema_path};",
        f"CREATE TAG IF NOT EXISTS {config.qualified(VERSION_TAG)}\n"
        f"    COMMENT = 'Immutable catalog_version a tagged catalog object was released at (D18).';",
    ]
    for table in ROW_TABLES:
        columns = ",\n".join(f"    {column}" for column in _TABLE_DDL[table])
        statements.append(f"CREATE TABLE IF NOT EXISTS {config.qualified(table)} (\n{columns}\n);")
    return statements


def _render_insert(config: ReleaseConfig, table: str, rows: list[Row]) -> str:
    columns = ", ".join(_COLUMNS[table])
    values = ",\n".join("    (" + ", ".join(_literal(value) for value in row) + ")" for row in rows)
    return f"INSERT INTO {config.qualified(table)}\n    ({columns})\nVALUES\n{values};"


def _render_tags(config: ReleaseConfig, version: str) -> list[str]:
    tag = config.qualified(VERSION_TAG)
    literal = _literal(version)
    statements = [f"ALTER SCHEMA {config.schema_path} SET TAG {tag} = {literal};"]
    statements.extend(f"ALTER TABLE {config.qualified(table)} SET TAG {tag} = {literal};" for table in ROW_TABLES)
    return statements


def render_release(
    catalog: Catalog,
    source: ReleaseSource,
    config: ReleaseConfig | None = None,
) -> tuple[str, ...]:
    """Render one catalog version as an ordered statement sequence: DDL, inserts, tags.

    Pure and deterministic — the same `(catalog, source, config)` always renders the identical
    tuple. `apply_release` executes these behind the immutability guard.
    """
    config = config or ReleaseConfig()
    statements = _render_ddl(config)
    statements.extend(_render_insert(config, table, rows) for table, rows in _rows(catalog, source).items() if rows)
    statements.extend(_render_tags(config, catalog.catalog_version))
    return tuple(statements)


def render_release_script(
    catalog: Catalog,
    source: ReleaseSource,
    config: ReleaseConfig | None = None,
) -> str:
    """The rendered release as one script — the plan a credential-free run prints (task 4.3)."""
    return "\n\n".join(render_release(catalog, source, config)) + "\n"


class ReleaseConnection(Protocol):
    """The thin warehouse boundary: one statement in, its result rows out.

    The deploy entrypoint adapts the snowflake driver to this (task 4.3); tests fake it. Keeping
    the surface to a single method means no snowflake import ever reaches this module or its
    tests, per the consumes posture (`task check` runs on a credential-free runner).
    """

    def execute(self, statement: str) -> list[tuple[object, ...]]: ...


@dataclass(frozen=True)
class ReleaseResult:
    """What an apply did: wrote the version, or found it already released and wrote nothing."""

    version: str
    status: Literal["applied", "already_released"]


class ReleaseConflictError(RuntimeError):
    """The target version exists with a different checksum — released rows are never rewritten.

    Raised before any insert. Carries the version and both checksums so the failure names
    exactly what disagrees, per D18: no hand edit, re-release, or job bug may change released
    rows.
    """

    def __init__(self, version: str, released_checksum: str, release_checksum: str) -> None:
        self.version = version
        self.released_checksum = released_checksum
        self.release_checksum = release_checksum
        super().__init__(
            f"catalog version {version} is already released with checksum {released_checksum}; "
            f"refusing to apply a release with checksum {release_checksum} — "
            "released rows are immutable (D18)"
        )


def _guard_query(config: ReleaseConfig, version: str) -> str:
    # Identifiers are validated by `ReleaseConfig` and the version goes through `_literal`,
    # the same escaping every rendered row uses — nothing user-controlled is interpolated raw.
    return f"SELECT CONTENT_CHECKSUM FROM {config.qualified('VERSIONS')} WHERE CATALOG_VERSION = {_literal(version)};"  # noqa: S608


def released_checksum(connection: ReleaseConnection, config: ReleaseConfig, version: str) -> str | None:
    """The checksum the warehouse recorded for `version`, or None if it was never released."""
    rows = connection.execute(_guard_query(config, version))
    checksums = sorted({str(row[0]) for row in rows})
    if not checksums:
        return None
    if len(checksums) > 1:
        msg = (
            f"catalog version {version} has {len(rows)} version rows with disagreeing checksums "
            f"{checksums} — the warehouse violates the one-row-per-version invariant"
        )
        raise RuntimeError(msg)
    return checksums[0]


def apply_release(
    catalog: Catalog,
    source: ReleaseSource,
    connection: ReleaseConnection,
    config: ReleaseConfig | None = None,
) -> ReleaseResult:
    """Execute one rendered release behind the immutability guard.

    Order matters, and each step is load-bearing:

    1. DDL — `CREATE ... IF NOT EXISTS`, idempotent and row-writing nothing, so the guard query
       has a `VERSIONS` table to read on an empty account. Snowflake DDL auto-commits, so it
       cannot live inside the write transaction anyway.
    2. The guard — read the version row. Present with the release's checksum: return
       `already_released` having written nothing. Present with a different checksum: raise
       `ReleaseConflictError` before any insert. Absent: proceed.
    3. The writes — every insert and tag inside one BEGIN/COMMIT, rolled back on any failure,
       so a partially released version is never visible.
    """
    config = config or ReleaseConfig()
    version = catalog.catalog_version

    for statement in _render_ddl(config):
        connection.execute(statement)

    existing = released_checksum(connection, config, version)
    if existing == source.snapshot_checksum:
        return ReleaseResult(version=version, status="already_released")
    if existing is not None:
        raise ReleaseConflictError(version, existing, source.snapshot_checksum)

    writes = [_render_insert(config, table, rows) for table, rows in _rows(catalog, source).items() if rows]
    writes.extend(_render_tags(config, version))

    connection.execute("BEGIN;")
    try:
        for statement in writes:
            connection.execute(statement)
    except BaseException:
        connection.execute("ROLLBACK;")
        raise
    connection.execute("COMMIT;")
    return ReleaseResult(version=version, status="applied")
