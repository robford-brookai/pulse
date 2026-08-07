"""Release-snapshot immutability gate for the authoritative catalog (catalog-authority 2.2).

Every released catalog version is frozen as a byte-identical snapshot at
`catalog/releases/v<version>.yaml` and recorded in the append-only checksum manifest
`catalog/releases/MANIFEST.sha256` (`<sha256>  v<version>.yaml`, `sha256sum -c` compatible,
oldest release first). `verify_snapshots` is the offline gate `task check` runs: the head
catalog must equal the snapshot of its own `catalog_version`, and every snapshot must match
its manifest checksum — a rewritten history is a hard failure naming the version.

`checksum_bytes` is the one checksum definition (sha256 of the snapshot file bytes) the
manifest, the warehouse version row, and the release guard all share (design decision 5/7).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pulse_core.catalog_gen import CATALOG_PATH

RELEASES_DIR = CATALOG_PATH.parent / "releases"
MANIFEST_NAME = "MANIFEST.sha256"

_MANIFEST_LINE = re.compile(r"^(?P<checksum>[0-9a-f]{64})  (?P<filename>v(?P<version>\S+)\.yaml)$")


@dataclass(frozen=True)
class ManifestEntry:
    """One append-only manifest row: a released version and the sha256 of its frozen snapshot."""

    version: str
    checksum: str
    filename: str


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manifest(path: Path) -> list[ManifestEntry]:
    """Parse the manifest, preserving append order (oldest release first)."""
    entries = []
    for line in path.read_text().splitlines():
        match = _MANIFEST_LINE.match(line)
        if match is None:
            msg = f"malformed manifest line in {path.name}: {line!r}"
            raise ValueError(msg)
        entries.append(ManifestEntry(match["version"], match["checksum"], match["filename"]))
    return entries


def verify_snapshots(catalog_path: Path = CATALOG_PATH, releases_dir: Path = RELEASES_DIR) -> list[str]:
    """Return every immutability violation, each naming the version whose history was rewritten."""
    manifest_path = releases_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"checksum manifest {manifest_path} is missing"]
    entries = read_manifest(manifest_path)

    errors = []
    for entry in entries:
        snapshot_path = releases_dir / entry.filename
        if not snapshot_path.is_file():
            errors.append(f"snapshot for version {entry.version} is missing: {snapshot_path}")
        elif checksum_bytes(snapshot_path.read_bytes()) != entry.checksum:
            errors.append(
                f"snapshot for version {entry.version} no longer matches its manifest checksum — history was rewritten"
            )

    head_bytes = catalog_path.read_bytes()
    head_version = str(yaml.safe_load(head_bytes)["catalog_version"])
    if head_version not in {entry.version for entry in entries}:
        errors.append(f"head catalog version {head_version} has no manifest entry")
    else:
        snapshot_path = releases_dir / f"v{head_version}.yaml"
        if snapshot_path.is_file() and snapshot_path.read_bytes() != head_bytes:
            errors.append(
                f"head catalog diverges from its release snapshot for version {head_version} — "
                f"released history was rewritten"
            )
    return errors
