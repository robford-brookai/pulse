"""Task 1.1 — manifest format round-trips (spec: Generation is byte-identical and receipted)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from synthea_seed.manifest import (
    MANIFEST_FORMAT,
    Manifest,
    build_manifest,
    compute_top_hash,
    read_manifest,
    verify_tree,
    write_manifest,
)


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Path:
    root = tmp_path / "population"
    _make_tree(
        root,
        {
            "fhir/patient-0001.json": '{"resourceType": "Bundle", "id": "synthetic-0001"}',
            "fhir/patient-0002.json": '{"resourceType": "Bundle", "id": "synthetic-0002"}',
            "fhir/hospitalInformation.json": '{"resourceType": "Bundle"}',
        },
    )
    return root


class TestRoundTrip:
    def test_manifest_round_trips_through_json(self, fixture_tree: Path) -> None:
        built = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=20260809)
        parsed = Manifest.from_json(built.to_json())
        assert parsed == built

    def test_manifest_round_trips_through_a_file(self, fixture_tree: Path, tmp_path: Path) -> None:
        built = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=20260809)
        path = tmp_path / "manifests" / "dev.manifest.json"
        write_manifest(built, path)
        assert read_manifest(path) == built

    def test_serialized_form_uses_the_declared_format_key(self, fixture_tree: Path) -> None:
        built = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=20260809)
        assert f'"format": "{MANIFEST_FORMAT}"' in built.to_json()


class TestManifestValidation:
    def test_unknown_format_is_rejected(self, fixture_tree: Path) -> None:
        built = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=1)
        raw = built.model_dump(by_alias=True)
        raw["format"] = "synthea-seed/manifest@2"
        with pytest.raises(ValidationError, match="format"):
            Manifest.model_validate(raw)

    def test_inconsistent_top_hash_is_rejected(self, fixture_tree: Path) -> None:
        built = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=1)
        raw = built.model_dump(by_alias=True)
        raw["top_hash"] = "0" * 64
        with pytest.raises(ValidationError, match="top_hash"):
            Manifest.model_validate(raw)

    def test_top_hash_is_order_independent(self) -> None:
        files = {"b.json": "1" * 64, "a.json": "2" * 64}
        reordered = dict(sorted(files.items(), reverse=True))
        assert compute_top_hash(files) == compute_top_hash(reordered)


class TestVerification:
    def test_identical_tree_verifies_clean(self, fixture_tree: Path) -> None:
        manifest = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=1)
        divergence = verify_tree(fixture_tree, manifest)
        assert divergence.ok
        assert divergence.describe() == ""

    def test_divergence_names_every_kind_of_difference(self, fixture_tree: Path) -> None:
        manifest = build_manifest(fixture_tree, profile="dev", synthea_version="v3.3.0", seed=1)
        (fixture_tree / "fhir/patient-0001.json").write_text('{"resourceType": "Bundle", "id": "mutated"}')
        (fixture_tree / "fhir/patient-0002.json").unlink()
        (fixture_tree / "fhir/patient-9999.json").write_text("{}")
        divergence = verify_tree(fixture_tree, manifest)
        assert not divergence.ok
        assert divergence.changed == ("fhir/patient-0001.json",)
        assert divergence.missing == ("fhir/patient-0002.json",)
        assert divergence.unexpected == ("fhir/patient-9999.json",)
        report = divergence.describe()
        assert "changed: fhir/patient-0001.json" in report
        assert "missing: fhir/patient-0002.json" in report
        assert "unexpected: fhir/patient-9999.json" in report
