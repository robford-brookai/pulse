"""The D18 immutability guard and plan/apply execution: released rows are never rewritten.

Covers the `catalog-release` spec scenarios "An identical re-release is a no-op" and "A
conflicting re-release fails before any write". Everything here is offline: the warehouse is a
fake behind the thin `ReleaseConnection` boundary, and no snowflake driver is imported.
"""

from __future__ import annotations

import re
import sys

import pytest
from pulse_core import catalog_release
from pulse_core.catalog_gen import Catalog
from pulse_core.catalog_release import (
    ReleaseConfig,
    ReleaseConflictError,
    ReleaseSource,
    apply_release,
)
from pulse_core.catalog_snapshots import checksum_bytes

CHECKSUM = checksum_bytes(b"the released snapshot")

SOURCE = ReleaseSource(
    git_commit="0" * 40,
    git_ref="refs/heads/main",
    snapshot_checksum=CHECKSUM,
)

_GUARD_VERSION = re.compile(r"CATALOG_VERSION = '([^']*)'")


def tiny_catalog() -> Catalog:
    """A minimal but complete catalog — one of every row kind, so writes are observable."""
    return Catalog.model_validate({
        "catalog_version": "1.0.0",
        "subjects": {"referral": {"ownership": "ledger", "transitions": {"received": ["closed"], "closed": []}}},
        "commands": {},
        "valuesets": {"referral_closure_reason": {"description": "Why it closed.", "codes": {"deceased": "Dead."}}},
        "programs": {"pcm": {"display_name": "Principal Care Management"}},
    })


class FakeConnection:
    """The thin boundary, faked: records every statement and answers the guard query."""

    def __init__(self, released: dict[str, str] | None = None) -> None:
        self.released = dict(released or {})
        self.executed: list[str] = []

    def execute(self, statement: str) -> list[tuple[object, ...]]:
        self.executed.append(statement)
        if statement.lstrip().startswith("SELECT"):
            match = _GUARD_VERSION.search(statement)
            assert match is not None, f"guard query has no version filter: {statement}"
            version = match.group(1)
            if version in self.released:
                return [(self.released[version],)]
            return []
        return []

    def writes(self) -> list[str]:
        """Statements that write rows or tags — everything the no-op and the guard must block."""
        return [
            statement for statement in self.executed if statement.startswith(("INSERT", "ALTER", "BEGIN", "COMMIT"))
        ]


class FailingConnection(FakeConnection):
    """Fails on the first INSERT, to observe the transaction unwind."""

    def execute(self, statement: str) -> list[tuple[object, ...]]:
        if statement.startswith("INSERT"):
            self.executed.append(statement)
            msg = "warehouse rejected the insert"
            raise RuntimeError(msg)
        return super().execute(statement)


def test_no_snowflake_driver_is_imported_at_test_time() -> None:
    assert not any(name == "snowflake" or name.startswith("snowflake.") for name in sys.modules)


def test_a_fresh_version_applies_every_write_in_a_single_transaction() -> None:
    connection = FakeConnection()
    result = apply_release(tiny_catalog(), SOURCE, connection)

    assert result.status == "applied"
    assert result.version == "1.0.0"
    begin = connection.executed.index("BEGIN;")
    commit = connection.executed.index("COMMIT;")
    writes = [i for i, s in enumerate(connection.executed) if s.startswith(("INSERT", "ALTER"))]
    assert writes, "an apply must execute the rendered inserts and tags"
    assert all(begin < i < commit for i in writes)


def test_an_apply_creates_objects_before_the_guard_looks_for_the_version_row() -> None:
    connection = FakeConnection()
    apply_release(tiny_catalog(), SOURCE, connection)

    guard = next(i for i, s in enumerate(connection.executed) if s.lstrip().startswith("SELECT"))
    ddl = [i for i, s in enumerate(connection.executed) if s.startswith("CREATE")]
    assert ddl and max(ddl) < guard, "the guard query needs the VERSIONS table to exist"


def test_an_apply_executes_exactly_the_rendered_release() -> None:
    catalog = tiny_catalog()
    connection = FakeConnection()
    apply_release(catalog, SOURCE, connection)

    rendered = list(catalog_release.render_release(catalog, SOURCE))
    executed_release = [
        statement
        for statement in connection.executed
        if not statement.lstrip().startswith("SELECT") and statement not in ("BEGIN;", "COMMIT;")
    ]
    assert executed_release == rendered


def test_an_identical_rerelease_writes_nothing_and_reports_already_released() -> None:
    connection = FakeConnection(released={"1.0.0": CHECKSUM})
    result = apply_release(tiny_catalog(), SOURCE, connection)

    assert result.status == "already_released"
    assert result.version == "1.0.0"
    assert connection.writes() == []


def test_a_conflicting_rerelease_fails_before_any_insert() -> None:
    existing = checksum_bytes(b"an earlier, different snapshot")
    connection = FakeConnection(released={"1.0.0": existing})

    with pytest.raises(ReleaseConflictError) as excinfo:
        apply_release(tiny_catalog(), SOURCE, connection)

    assert connection.writes() == []
    message = str(excinfo.value)
    assert "1.0.0" in message
    assert existing in message
    assert CHECKSUM in message


def test_the_conflict_error_carries_version_and_both_checksums() -> None:
    existing = checksum_bytes(b"an earlier, different snapshot")
    connection = FakeConnection(released={"1.0.0": existing})

    with pytest.raises(ReleaseConflictError) as excinfo:
        apply_release(tiny_catalog(), SOURCE, connection)

    assert excinfo.value.version == "1.0.0"
    assert excinfo.value.released_checksum == existing
    assert excinfo.value.release_checksum == CHECKSUM


def test_the_guard_compares_the_shared_checksum_definition() -> None:
    """Manifest, version row, and guard share one checksum: sha256 of the snapshot bytes.

    A warehouse row recorded via `checksum_bytes` must satisfy a release sourced via
    `snapshot_checksum` — the two ends of the pipeline agree byte for byte.
    """
    version = "1.0.0"
    snapshot = (catalog_release.RELEASES_DIR / f"v{version}.yaml").read_bytes()
    source = ReleaseSource(
        git_commit="0" * 40,
        git_ref="refs/heads/main",
        snapshot_checksum=catalog_release.snapshot_checksum(version),
    )
    connection = FakeConnection(released={version: checksum_bytes(snapshot)})

    catalog = tiny_catalog()
    result = apply_release(catalog, source, connection)
    assert result.status == "already_released"


def test_a_duplicate_version_row_with_disagreeing_checksums_is_an_error() -> None:
    class CorruptConnection(FakeConnection):
        def execute(self, statement: str) -> list[tuple[object, ...]]:
            if statement.lstrip().startswith("SELECT"):
                self.executed.append(statement)
                return [("a" * 64,), ("b" * 64,)]
            return super().execute(statement)

    connection = CorruptConnection()
    with pytest.raises(RuntimeError, match=re.escape("1.0.0")):
        apply_release(tiny_catalog(), SOURCE, connection)
    assert connection.writes() == []


def test_a_failed_write_rolls_back_and_propagates() -> None:
    connection = FailingConnection()

    with pytest.raises(RuntimeError, match="rejected"):
        apply_release(tiny_catalog(), SOURCE, connection)

    assert "ROLLBACK;" in connection.executed
    assert "COMMIT;" not in connection.executed


def test_the_guard_queries_the_configured_versions_table() -> None:
    config = ReleaseConfig(database="SOME_DB")
    connection = FakeConnection()
    apply_release(tiny_catalog(), SOURCE, connection, config)

    guard = next(s for s in connection.executed if s.lstrip().startswith("SELECT"))
    assert "SOME_DB.CATALOG.VERSIONS" in guard
    assert "CATALOG_VERSION = '1.0.0'" in guard
