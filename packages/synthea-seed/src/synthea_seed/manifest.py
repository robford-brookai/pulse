"""Checksum manifest: the byte-identity receipt for a generated population.

Format (design.md decision 4): sha256 per output file plus a top hash over the sorted
(path, hash) pairs, serialized as JSON and committed. Verification compares a generated tree
against the committed manifest and reports every diverging file by name — drift is a failure,
not a refresh; the manifest changes only through an explicit re-pin.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MANIFEST_FORMAT = "synthea-seed/manifest@1"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_CHUNK = 1 << 20


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def compute_top_hash(files: dict[str, str]) -> str:
    """One hash over the sorted (path, sha256) pairs — order-independent by construction."""
    digest = hashlib.sha256()
    for rel_path, file_hash in sorted(files.items()):
        digest.update(rel_path.encode())
        digest.update(b"\x00")
        digest.update(file_hash.encode())
        digest.update(b"\n")
    return digest.hexdigest()


class Divergence(BaseModel):
    """Every way a tree can differ from its manifest, each file named."""

    model_config = ConfigDict(frozen=True)

    changed: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.changed or self.missing or self.unexpected)

    def describe(self) -> str:
        """Human-readable divergence report, one file per line."""
        lines: list[str] = []
        for label, names in (
            ("changed", self.changed),
            ("missing", self.missing),
            ("unexpected", self.unexpected),
        ):
            lines.extend(f"{label}: {name}" for name in names)
        return "\n".join(lines)


class Manifest(BaseModel):
    """The committed receipt: per-file checksums plus the pin that produced them."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    manifest_format: str = Field(alias="format")
    profile: str = Field(min_length=1)
    synthea_version: str = Field(min_length=1)
    seed: int
    files: dict[str, Sha256]
    top_hash: Sha256

    @model_validator(mode="after")
    def _internally_consistent(self) -> Manifest:
        if self.manifest_format != MANIFEST_FORMAT:
            msg = f"unsupported manifest format {self.manifest_format!r}; expected {MANIFEST_FORMAT!r}"
            raise ValueError(msg)
        expected = compute_top_hash(self.files)
        if self.top_hash != expected:
            msg = f"top_hash {self.top_hash} does not match the files it claims to receipt ({expected})"
            raise ValueError(msg)
        return self

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        return cls.model_validate_json(text)


def _tree_files(root: Path) -> dict[str, str]:
    """sha256 per regular file under root, keyed by sorted posix-relative path."""
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    return {p.relative_to(root).as_posix(): _hash_file(p) for p in paths}


def build_manifest(root: Path, *, profile: str, synthea_version: str, seed: int) -> Manifest:
    """Author a manifest from a generated tree — the explicit re-pin path, never automatic."""
    files = _tree_files(root)
    return Manifest(
        format=MANIFEST_FORMAT,
        profile=profile,
        synthea_version=synthea_version,
        seed=seed,
        files=files,
        top_hash=compute_top_hash(files),
    )


def verify_tree(root: Path, manifest: Manifest) -> Divergence:
    """Compare a generated tree against its manifest, naming every diverging file."""
    actual = _tree_files(root)
    expected = manifest.files
    return Divergence(
        changed=tuple(sorted(p for p in expected if p in actual and actual[p] != expected[p])),
        missing=tuple(sorted(p for p in expected if p not in actual)),
        unexpected=tuple(sorted(p for p in actual if p not in expected)),
    )


def read_manifest(path: Path) -> Manifest:
    return Manifest.from_json(path.read_text())


def write_manifest(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.to_json())
