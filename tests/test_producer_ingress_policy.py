"""The §4.4 producer-policy gate: walks `packages/ocean` producer source under `task check`.

Wires the classifier (`pulse_core.producer_policy`, producer-ingress-policy 1.1) and the
suppression mechanism (2.1) into a repo-level test: classify the committed producer source
against the pinned catalog contract, apply the shipped suppression list, and fail naming every
unsuppressed finding and every suppression error. Offline, no network, no credentials — it reads
only committed source text and `pulse_core.generated.TRANSITIONS`.

Covers the producer-policy spec scenarios "The current tree passes the gate" and "A planted
state-bearing emit turns the gate red, and removal turns it green". The second scenario is the
Demo 2 mechanic run against a copied `tmp_path` scan tree, never `packages/ocean` itself.
"""

from __future__ import annotations

from pathlib import Path

from pulse_core.producer_policy import (
    apply_suppressions,
    classify_files,
    parse_suppressions,
    render_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OCEAN = REPO_ROOT / "packages" / "ocean"
SUPPRESSIONS_PATH = OCEAN / "producer-policy-suppressions.yaml"

#: Producer source roots, per the spec: ocean's shared libs, its services, and its scripts.
#: `libs/*/src` and `services/*/src` are each package's importable surface; `tests/`, `docs/`,
#: `.venv/`, and cache directories are never producer source even when nested under one of
#: these roots, so they are excluded defensively rather than assumed absent.
_EXCLUDED_DIR_NAMES = frozenset({"tests", "docs", ".venv", "__pycache__"})


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_DIR_NAMES for part in path.parts)


def _producer_source_roots(ocean_root: Path) -> list[Path]:
    roots = sorted((ocean_root / "libs").glob("*/src")) + sorted((ocean_root / "services").glob("*/src"))
    scripts = ocean_root / "scripts"
    if scripts.is_dir():
        roots.append(scripts)
    return roots


def producer_source_paths(ocean_root: Path) -> list[Path]:
    """Every producer `.py` file under `libs/*/src`, `services/*/src`, and `scripts/`.

    Sorted before returning: findings must not depend on filesystem iteration order (the same
    discipline `classify_files` already applies to its own input).
    """
    paths: set[Path] = set()
    for root in _producer_source_roots(ocean_root):
        for path in root.rglob("*.py"):
            if not _is_excluded(path.relative_to(ocean_root)):
                paths.add(path)
    return sorted(paths)


def run_gate(ocean_root: Path, suppressions_path: Path) -> tuple[list, list]:
    """Classify `ocean_root`'s producer source, apply `suppressions_path`, return (findings, errors)."""
    findings = classify_files(producer_source_paths(ocean_root), root=ocean_root)
    entries = parse_suppressions(suppressions_path.read_text(encoding="utf-8"))
    surviving, errors = apply_suppressions(findings, entries)
    return surviving, errors


# --- The current tree passes the gate ------------------------------------------------------


def test_the_committed_ocean_tree_passes_the_gate() -> None:
    findings, errors = run_gate(OCEAN, SUPPRESSIONS_PATH)

    assert findings == [], render_report(findings)
    assert errors == []


def test_the_gate_discovers_producer_source_files() -> None:
    # A gate that walks nothing passes vacuously. Pin that the walk actually finds ocean's
    # real producer source, so an accidental empty-list return can't masquerade as green.
    paths = producer_source_paths(OCEAN)

    assert len(paths) > 50
    assert all(path.suffix == ".py" for path in paths)


def test_the_walk_excludes_tests_docs_and_cache_directories() -> None:
    paths = producer_source_paths(OCEAN)

    assert not any(_EXCLUDED_DIR_NAMES & set(p.relative_to(OCEAN).parts) for p in paths)


# --- A planted state-bearing emit turns the gate red, and removal turns it green ------------

_PLANTED_SCHEMA = '''
"""A planted producer schema asserting referral state (Demo 2 mechanic, against tmp_path)."""

from typing import Literal

ReferralStatus = Literal["screened", "outreach", "converted"]
'''

_EMPTY_SUPPRESSIONS = "suppressions: []\n"


def _copy_ocean_scan_tree(tmp_path: Path) -> Path:
    """A minimal copy of ocean's real shape: one lib with a `src/` producer file."""
    scan_root = tmp_path / "ocean"
    lib_src = scan_root / "libs" / "ocean-events" / "src" / "ocean_events"
    lib_src.mkdir(parents=True)
    (lib_src / "types.py").write_text('EventKind = Literal["received", "processed"]\n', encoding="utf-8")
    return scan_root


def test_a_planted_state_bearing_emit_turns_the_gate_red_and_removal_turns_it_green(tmp_path: Path) -> None:
    scan_root = _copy_ocean_scan_tree(tmp_path)
    suppressions_path = tmp_path / "producer-policy-suppressions.yaml"
    suppressions_path.write_text(_EMPTY_SUPPRESSIONS, encoding="utf-8")

    findings, errors = run_gate(scan_root, suppressions_path)
    assert findings == []
    assert errors == []

    planted = scan_root / "libs" / "ocean-events" / "src" / "ocean_events" / "planted.py"
    planted.write_text(_PLANTED_SCHEMA, encoding="utf-8")

    findings, errors = run_gate(scan_root, suppressions_path)
    assert [(f.file, f.element, f.subject, f.states) for f in findings] == [
        (
            "libs/ocean-events/src/ocean_events/planted.py",
            "ReferralStatus",
            "referral",
            ("converted", "outreach", "screened"),
        )
    ]
    assert errors == []

    planted.unlink()

    findings, errors = run_gate(scan_root, suppressions_path)
    assert findings == []
    assert errors == []


# --- Suppression errors also fail the gate --------------------------------------------------


def test_a_stale_or_unjustified_suppression_fails_the_gate(tmp_path: Path) -> None:
    scan_root = _copy_ocean_scan_tree(tmp_path)
    suppressions_path = tmp_path / "producer-policy-suppressions.yaml"
    suppressions_path.write_text(
        """
suppressions:
  - file: libs/ocean-events/src/ocean_events/types.py
    element: NeverFound
    subject: referral
    justification: "adjudicated false positive"
""",
        encoding="utf-8",
    )

    findings, errors = run_gate(scan_root, suppressions_path)

    assert findings == []
    assert len(errors) == 1
    assert errors[0].reason == "matches no current finding"
