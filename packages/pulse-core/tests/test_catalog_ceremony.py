"""The migration ceremony gate: breaking releases pay the MAJOR bump plus a migration note.

Covers the `catalog-versioning` spec scenarios "A breaking release without a migration note
fails the check" and "A conformant breaking release passes". The committed-tree test is the
gate itself — it runs under `task check`, offline, in a fresh clone; the tmp-tree tests prove
the gate fails a breaking diff missing either artifact, naming what is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pulse_core import catalog_ceremony, catalog_snapshots

REPO_ROOT = Path(__file__).parents[3]

CHECKLIST_NOTE = (
    "# Migration: v2.0.0\n\n"
    "- [ ] Twenty metadata redeploy\n"
    "- [ ] ConceptMap regeneration\n"
    "- [ ] rule_version bump if verdict criteria reference the changed codes\n"
)


def catalog_dict(version: str, transitions: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """A valid catalog document; only the version and the referral adjacency vary per test."""
    if transitions is None:
        transitions = {
            "received": ["resolved", "closed"],
            "resolved": ["closed"],
            "closed": [],
        }
    return {
        "catalog_version": version,
        "subjects": {"referral": {"ownership": "ledger", "transitions": transitions}},
        "commands": {"record_referral": {"subject_type": "referral"}},
        "valuesets": {
            "referral_closure_reason": {
                "description": "Why a referral closed.",
                "codes": {"deceased": "Deceased", "duplicate": "Duplicate"},
            },
        },
        "programs": {"pcm": {"display_name": "Principal Care Management"}},
    }


BREAKING_TRANSITIONS = {"received": ["closed"], "closed": []}  # drops the `resolved` state


def write_releases(root: Path, versions: dict[str, dict[str, Any]]) -> Path:
    """Freeze each catalog document as a snapshot and record it in the manifest, in order."""
    releases_dir = root / "catalog" / "releases"
    releases_dir.mkdir(parents=True)
    manifest_lines = []
    for version, document in versions.items():
        content = yaml.safe_dump(document, sort_keys=False)
        (releases_dir / f"v{version}.yaml").write_text(content)
        manifest_lines.append(f"{catalog_snapshots.checksum_bytes(content.encode())}  v{version}.yaml")
    (releases_dir / catalog_snapshots.MANIFEST_NAME).write_text("\n".join(manifest_lines) + "\n")
    return releases_dir


def test_module_default_path_points_at_the_repo_tree() -> None:
    assert catalog_ceremony.RELEASES_DIR == REPO_ROOT / "catalog" / "releases"


def test_gate_passes_on_the_committed_tree() -> None:
    """The gate `task check` runs: the two newest released versions honor the ceremony."""
    assert catalog_ceremony.verify_ceremony() == []


def test_single_release_has_nothing_to_classify(tmp_path: Path) -> None:
    releases_dir = write_releases(tmp_path, {"1.0.0": catalog_dict("1.0.0")})

    assert catalog_ceremony.verify_ceremony(releases_dir) == []


def test_additive_release_needs_no_ceremony(tmp_path: Path) -> None:
    widened = catalog_dict("1.1.0")
    widened["valuesets"]["referral_closure_reason"]["codes"]["moved"] = "Moved away"
    releases_dir = write_releases(tmp_path, {"1.0.0": catalog_dict("1.0.0"), "1.1.0": widened})

    assert catalog_ceremony.verify_ceremony(releases_dir) == []


def test_breaking_release_without_note_or_bump_fails_naming_both_artifacts(tmp_path: Path) -> None:
    releases_dir = write_releases(
        tmp_path,
        {"1.0.0": catalog_dict("1.0.0"), "1.1.0": catalog_dict("1.1.0", BREAKING_TRANSITIONS)},
    )

    errors = catalog_ceremony.verify_ceremony(releases_dir)

    assert any("major" in error.lower() and "1.1.0" in error for error in errors)
    assert any("v1.1.0-migration.md" in error for error in errors)


def test_breaking_release_with_bump_but_no_note_fails_naming_the_note(tmp_path: Path) -> None:
    releases_dir = write_releases(
        tmp_path,
        {"1.0.0": catalog_dict("1.0.0"), "2.0.0": catalog_dict("2.0.0", BREAKING_TRANSITIONS)},
    )

    errors = catalog_ceremony.verify_ceremony(releases_dir)

    assert len(errors) == 1
    assert "v2.0.0-migration.md" in errors[0]


def test_breaking_release_with_note_but_unbumped_major_fails_naming_the_bump(tmp_path: Path) -> None:
    releases_dir = write_releases(
        tmp_path,
        {"1.0.0": catalog_dict("1.0.0"), "1.1.0": catalog_dict("1.1.0", BREAKING_TRANSITIONS)},
    )
    (releases_dir / "v1.1.0-migration.md").write_text(CHECKLIST_NOTE)

    errors = catalog_ceremony.verify_ceremony(releases_dir)

    assert len(errors) == 1
    assert "major" in errors[0].lower()
    assert "1.1.0" in errors[0]


def test_conformant_breaking_release_passes(tmp_path: Path) -> None:
    releases_dir = write_releases(
        tmp_path,
        {"1.0.0": catalog_dict("1.0.0"), "2.0.0": catalog_dict("2.0.0", BREAKING_TRANSITIONS)},
    )
    (releases_dir / "v2.0.0-migration.md").write_text(CHECKLIST_NOTE)

    assert catalog_ceremony.verify_ceremony(releases_dir) == []


def test_empty_migration_note_fails_naming_the_note(tmp_path: Path) -> None:
    """A zero-byte note carries no consumer checklist — it is the missing artifact with a name."""
    releases_dir = write_releases(
        tmp_path,
        {"1.0.0": catalog_dict("1.0.0"), "2.0.0": catalog_dict("2.0.0", BREAKING_TRANSITIONS)},
    )
    (releases_dir / "v2.0.0-migration.md").write_text("\n")

    errors = catalog_ceremony.verify_ceremony(releases_dir)

    assert len(errors) == 1
    assert "v2.0.0-migration.md" in errors[0]


def test_error_names_what_made_the_release_breaking(tmp_path: Path) -> None:
    releases_dir = write_releases(
        tmp_path,
        {"1.0.0": catalog_dict("1.0.0"), "1.1.0": catalog_dict("1.1.0", BREAKING_TRANSITIONS)},
    )

    errors = catalog_ceremony.verify_ceremony(releases_dir)

    assert any("resolved" in error for error in errors)
