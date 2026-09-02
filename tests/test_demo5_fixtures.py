"""Demo 5 fixture overlay (pulse-demo-closeout task 1.1): a `synthea-seed` overlay plus the
raw referral/consent/verdict fixtures, all keyed to one synthetic patient, committed with a
checksum manifest.

Two things are pinned here: the overlay is valid under the `synthetic-population` overlay
validator (`synthea_seed.overlays.load_overlay`), and the three raw fixture files agree with
each other and the overlay on the patient's identifier — a demo stage that reads any one of
them and compares against another must see the same key.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from synthea_seed.overlays import OVERLAY_FORMAT, load_overlay

REPO_ROOT = Path(__file__).parents[1]
FIXTURES_DIR = REPO_ROOT / "scripts" / "demo" / "fixtures"
OVERLAY_PATH = FIXTURES_DIR / "overlay.yaml"
REFERRALS_PATH = FIXTURES_DIR / "referral_variants.json"
CONSENT_ROW_PATH = FIXTURES_DIR / "consent_export_row.json"
VERDICT_ROW_PATH = FIXTURES_DIR / "verdict_mart_row.json"
MANIFEST_PATH = FIXTURES_DIR / "MANIFEST.md"

PATIENT_ID = "brook-fx-demo5-episode-0001"

#: `| MANIFEST.md \| \`<file>\` \| \`<64-hex-sha256>\` \|` — one row per fixture file.
_MANIFEST_ROW = re.compile(r"^\|\s*`(?P<file>[^`]+)`\s*\|\s*`(?P<sha256>[0-9a-f]{64})`\s*\|$", re.MULTILINE)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_overlay_passes_the_synthetic_population_overlay_validator() -> None:
    overlay = load_overlay(OVERLAY_PATH)
    assert overlay.overlay_format == OVERLAY_FORMAT
    assert overlay.fixture == "demo5_end_to_end_episode"
    assert [patient.patient_id for patient in overlay.patients] == [PATIENT_ID]


def test_overlay_engineers_the_billing_verdict_and_consent_this_demo_needs() -> None:
    overlay = load_overlay(OVERLAY_PATH)
    (patient,) = overlay.patients
    assert len(patient.state.billing_episodes) == 1
    assert len(patient.state.verdicts) == 1
    assert len(patient.state.consents) == 1
    assert patient.state.billing_episodes[0].qualification_verdict == "qualified"


def test_referral_variants_cover_mint_exact_match_and_quarantine() -> None:
    variants = _load_json(REFERRALS_PATH)["variants"]
    by_case = {variant["case"]: variant for variant in variants}
    assert set(by_case) == {"mint", "exact_match", "quarantine"}
    assert by_case["mint"]["expected_decision"] == "mint"
    assert by_case["mint"]["existing_persons"] == []
    assert by_case["exact_match"]["expected_decision"] == "match"
    assert by_case["exact_match"]["expected_person_id"] == PATIENT_ID
    assert by_case["quarantine"]["expected_decision"] == "ambiguous"
    assert PATIENT_ID in by_case["quarantine"]["expected_candidate_person_ids"]


def test_the_three_fixture_files_agree_on_the_patients_identifiers() -> None:
    """`referral_variants.json`, `consent_export_row.json`, and `verdict_mart_row.json` must
    name the same patient the overlay engineers — a stage comparing any two of them on subject
    key is comparing the same patient, never a drifted one."""
    variants = _load_json(REFERRALS_PATH)["variants"]
    by_case = {variant["case"]: variant for variant in variants}
    referral_resolved_person_id = by_case["exact_match"]["expected_person_id"]

    consent_row = _load_json(CONSENT_ROW_PATH)
    verdict_row = _load_json(VERDICT_ROW_PATH)
    overlay = load_overlay(OVERLAY_PATH)
    (overlay_patient_id,) = [patient.patient_id for patient in overlay.patients]

    assert referral_resolved_person_id == PATIENT_ID
    assert consent_row["subject_key"] == PATIENT_ID
    assert verdict_row["subject_id"] == PATIENT_ID
    assert overlay_patient_id == PATIENT_ID


def test_consent_row_carries_the_pinned_landing_contract_columns() -> None:
    row = _load_json(CONSENT_ROW_PATH)
    for column in ("subject_key", "channel", "to_state", "message_id", "event_time"):
        assert column in row, f"consent_export_row.json missing contract column {column!r}"


def test_verdict_row_carries_the_pinned_mart_contract_columns_and_a_registered_type() -> None:
    row = _load_json(VERDICT_ROW_PATH)
    for column in (
        "subject_id",
        "verdict_type",
        "outcome",
        "reason",
        "rule_version",
        "as_of",
        "lineage_ref",
        "computed_at",
    ):
        assert column in row, f"verdict_mart_row.json missing contract column {column!r}"
    # Registered against `billing_episode` (packages/verdict-relay/src/verdict_relay/config.py);
    # an unregistered type would fail the relay before any declaration.
    assert row["verdict_type"] == "billing_eligibility"


def test_manifest_checksums_match_the_committed_fixture_files() -> None:
    manifest_text = MANIFEST_PATH.read_text()
    rows = _MANIFEST_ROW.findall(manifest_text)
    assert rows, "MANIFEST.md has no checksum rows to verify"
    checked = {name for name, _ in rows}
    assert checked == {"overlay.yaml", "referral_variants.json", "consent_export_row.json", "verdict_mart_row.json"}
    for file_name, expected_sha256 in rows:
        actual_sha256 = hashlib.sha256((FIXTURES_DIR / file_name).read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256, f"{file_name} has drifted from MANIFEST.md's checksum"
