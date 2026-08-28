"""Migration-ceremony gate for breaking catalog releases (catalog-authority 3.2).

Composes the D18 classifier (task 3.1) over the two newest manifest versions (task 2.2): when
their diff is breaking under runtime-readiness §4.3, the release must have incremented the
MAJOR version and shipped `catalog/releases/v<version>-migration.md` carrying the consumer
checklist — Twenty metadata redeploy, ConceptMap regeneration, rule_version bump if verdict
criteria reference the changed codes. `verify_ceremony` is the offline gate `task check` runs;
each violation names the missing artifact and what made the release breaking, so the ceremony
is enforced by CI, not convention.

With fewer than two released versions there is no diff to classify and the gate passes; a
non-breaking diff needs no ceremony.
"""

from __future__ import annotations

from pathlib import Path

from pulse_core.catalog_breaking import ReleaseClassification, classify_release
from pulse_core.catalog_gen import load_catalog
from pulse_core.catalog_snapshots import MANIFEST_NAME, RELEASES_DIR, read_manifest


def _major(version: str) -> int:
    return int(version.split(".")[0])


def _because(classification: ReleaseClassification) -> str:
    return "; ".join(finding.message for finding in classification.findings)


def verify_ceremony(releases_dir: Path = RELEASES_DIR) -> list[str]:
    """Return every ceremony violation between the two newest released versions."""
    entries = read_manifest(releases_dir / MANIFEST_NAME)
    if len(entries) < 2:
        return []

    previous, current = entries[-2], entries[-1]
    classification = classify_release(
        load_catalog(releases_dir / previous.filename),
        load_catalog(releases_dir / current.filename),
    )
    if not classification.breaking:
        return []

    errors = []
    if _major(current.version) <= _major(previous.version):
        errors.append(
            f"release {current.version} is breaking relative to {previous.version} but did not "
            f"increment the MAJOR version ({_because(classification)})"
        )
    note_path = releases_dir / f"v{current.version}-migration.md"
    if not note_path.is_file() or not note_path.read_text().strip():
        errors.append(
            f"release {current.version} is breaking relative to {previous.version} but its "
            f"migration note v{current.version}-migration.md is missing or empty — it must carry "
            f"the consumer checklist ({_because(classification)})"
        )
    return errors
