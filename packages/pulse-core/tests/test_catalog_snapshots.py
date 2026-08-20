"""Release-snapshot immutability gate: head == current snapshot, every snapshot == its checksum.

Covers the `catalog-versioning` spec scenarios "The head catalog matches its release snapshot"
and "A tampered snapshot fails the gate". The committed-tree test is the gate itself — it runs
under `task check`, offline, in a fresh clone; the tmp-tree tests prove the gate actually fails
on a rewritten history, naming the version.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pulse_core import catalog_snapshots

REPO_ROOT = Path(__file__).parents[3]

HEAD_V1 = "catalog_version: 1.0.0\nsubjects: {}\n"
PAST_V0 = "catalog_version: 0.9.0\nsubjects: {}\n"


def write_tree(
    root: Path,
    head: str = HEAD_V1,
    snapshots: dict[str, str] | None = None,
    manifest_for: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Build a catalog tree; manifest checksums are taken from `manifest_for` (or the snapshots)."""
    if snapshots is None:
        snapshots = {"0.9.0": PAST_V0, "1.0.0": HEAD_V1}
    if manifest_for is None:
        manifest_for = snapshots
    catalog_path = root / "catalog" / "state_catalog.yaml"
    releases_dir = root / "catalog" / "releases"
    releases_dir.mkdir(parents=True)
    catalog_path.write_text(head)
    for version, content in snapshots.items():
        (releases_dir / f"v{version}.yaml").write_text(content)
    manifest_lines = [
        f"{catalog_snapshots.checksum_bytes(content.encode())}  v{version}.yaml"
        for version, content in manifest_for.items()
    ]
    (releases_dir / catalog_snapshots.MANIFEST_NAME).write_text("\n".join(manifest_lines) + "\n")
    return catalog_path, releases_dir


def test_module_default_paths_point_at_the_repo_tree() -> None:
    assert catalog_snapshots.CATALOG_PATH == REPO_ROOT / "catalog" / "state_catalog.yaml"
    assert catalog_snapshots.RELEASES_DIR == REPO_ROOT / "catalog" / "releases"


def test_gate_passes_on_the_committed_tree() -> None:
    """The gate: head catalog == its version's snapshot, every snapshot == its manifest checksum."""
    assert catalog_snapshots.verify_snapshots() == []


def test_committed_snapshot_is_a_byte_identical_copy_of_the_head_catalog() -> None:
    head = catalog_snapshots.CATALOG_PATH.read_bytes()
    snapshot = (catalog_snapshots.RELEASES_DIR / "v1.1.0.yaml").read_bytes()
    assert head == snapshot


def test_consistent_tmp_tree_passes(tmp_path: Path) -> None:
    catalog_path, releases_dir = write_tree(tmp_path)
    assert catalog_snapshots.verify_snapshots(catalog_path, releases_dir) == []


def test_tampered_past_snapshot_fails_naming_the_version(tmp_path: Path) -> None:
    catalog_path, releases_dir = write_tree(tmp_path)
    (releases_dir / "v0.9.0.yaml").write_text("catalog_version: 0.9.0\nsubjects: {rewritten: {}}\n")

    errors = catalog_snapshots.verify_snapshots(catalog_path, releases_dir)

    assert len(errors) == 1
    assert "0.9.0" in errors[0]


def test_head_diverging_from_its_snapshot_fails_naming_the_version(tmp_path: Path) -> None:
    catalog_path, releases_dir = write_tree(tmp_path, head=HEAD_V1 + "commands: {}\n")

    errors = catalog_snapshots.verify_snapshots(catalog_path, releases_dir)

    assert len(errors) == 1
    assert "1.0.0" in errors[0]


def test_head_version_missing_from_the_manifest_fails(tmp_path: Path) -> None:
    catalog_path, releases_dir = write_tree(
        tmp_path,
        snapshots={"0.9.0": PAST_V0, "1.0.0": HEAD_V1},
        manifest_for={"0.9.0": PAST_V0},
    )

    errors = catalog_snapshots.verify_snapshots(catalog_path, releases_dir)

    assert any("1.0.0" in error and "manifest" in error for error in errors)


def test_snapshot_missing_for_a_manifest_entry_fails(tmp_path: Path) -> None:
    catalog_path, releases_dir = write_tree(tmp_path)
    (releases_dir / "v0.9.0.yaml").unlink()

    errors = catalog_snapshots.verify_snapshots(catalog_path, releases_dir)

    assert len(errors) == 1
    assert "0.9.0" in errors[0]


def test_missing_manifest_fails(tmp_path: Path) -> None:
    catalog_path, releases_dir = write_tree(tmp_path)
    (releases_dir / catalog_snapshots.MANIFEST_NAME).unlink()

    errors = catalog_snapshots.verify_snapshots(catalog_path, releases_dir)

    assert errors and "manifest" in errors[0]


def test_manifest_order_is_preserved_for_recency(tmp_path: Path) -> None:
    """Append-only manifest order is what 'two newest versions' (task 3.2) will read."""
    _, releases_dir = write_tree(tmp_path)

    entries = catalog_snapshots.read_manifest(releases_dir / catalog_snapshots.MANIFEST_NAME)

    assert [entry.version for entry in entries] == ["0.9.0", "1.0.0"]


def test_malformed_manifest_line_is_rejected(tmp_path: Path) -> None:
    _, releases_dir = write_tree(tmp_path)
    manifest = releases_dir / catalog_snapshots.MANIFEST_NAME
    manifest.write_text(manifest.read_text() + "not-a-manifest-line\n")

    with pytest.raises(ValueError, match="manifest"):
        catalog_snapshots.read_manifest(manifest)
