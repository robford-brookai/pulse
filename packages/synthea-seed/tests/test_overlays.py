"""Task 2.2 — overlay fixtures and application (spec: Engineered fixtures are declarative overlays).

Covers the scenarios "Overlays apply deterministically" and "Overlay validation rejects
malformed fixtures", plus the presence and engineered shape of each design-doc-named fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from synthea_seed.overlays import (
    DEFAULT_OVERLAY_DIR,
    NAMED_FIXTURES,
    Overlay,
    OverlayError,
    apply_overlays,
    load_overlay,
    load_overlay_set,
)


def _base_population() -> dict[str, dict[str, Any]]:
    return {
        "synthea-0001": {"resource": {"resourceType": "Bundle", "id": "synthea-0001"}},
        "synthea-0002": {"resource": {"resourceType": "Bundle", "id": "synthea-0002"}},
    }


def _minimal_overlay_raw(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "format": "synthea-seed/overlay@1",
        "fixture": "example_fixture",
        "design_ref": "design/example.md",
        "description": "an example",
        "patients": [
            {
                "patient_id": "brook-fx-example-0001",
                "state": {
                    "verdicts": [
                        {
                            "name": "qualification_assessment",
                            "outcome": "positive",
                            "rule_version": "rules-1",
                            "as_of": "2026-06-30",
                        }
                    ]
                },
            }
        ],
    }
    raw.update(overrides)
    return raw


def _write(tmp_path: Path, name: str, raw: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw))
    return path


class TestDeterministicApplication:
    def test_applying_twice_from_scratch_is_identical(self) -> None:
        overlays = load_overlay_set()
        first = apply_overlays(_base_population(), overlays)
        second = apply_overlays(_base_population(), overlays)
        assert first == second

    def test_double_apply_onto_the_result_is_idempotent(self) -> None:
        overlays = load_overlay_set()
        once = apply_overlays(_base_population(), overlays)
        twice = apply_overlays(once, overlays)
        assert once == twice

    def test_base_population_is_never_mutated(self) -> None:
        base = _base_population()
        snapshot = {pid: dict(record) for pid, record in base.items()}
        apply_overlays(base, load_overlay_set())
        assert base == snapshot

    def test_base_patients_survive_application(self) -> None:
        applied = apply_overlays(_base_population(), load_overlay_set())
        assert applied["synthea-0001"] == _base_population()["synthea-0001"]


class TestMalformedOverlays:
    def test_invalid_yaml_names_file_and_reason(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("format: [unclosed")
        with pytest.raises(OverlayError, match=r"broken\.yaml.*not valid YAML") as excinfo:
            load_overlay(path)
        assert excinfo.value.file_name == "broken.yaml"

    def test_indeterminate_without_reason_is_rejected(self, tmp_path: Path) -> None:
        raw = _minimal_overlay_raw()
        raw["patients"][0]["state"]["verdicts"][0] = {
            "name": "qualification_assessment",
            "outcome": "indeterminate",
            "rule_version": "rules-1",
            "as_of": "2026-06-30",
        }
        path = _write(tmp_path, "bad-verdict.yaml", raw)
        with pytest.raises(OverlayError, match=r"bad-verdict\.yaml") as excinfo:
            load_overlay(path)
        assert "mandatory reason" in excinfo.value.reason

    def test_unknown_key_is_rejected_naming_the_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "extra-key.yaml", _minimal_overlay_raw(surprise=True))
        with pytest.raises(OverlayError, match=r"extra-key\.yaml"):
            load_overlay(path)

    def test_wrong_format_marker_is_rejected(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "wrong-format.yaml", _minimal_overlay_raw(format="synthea-seed/overlay@9"))
        with pytest.raises(OverlayError, match=r"wrong-format\.yaml.*overlay@9"):
            load_overlay(path)

    def test_ended_enrollment_without_reason_is_rejected(self, tmp_path: Path) -> None:
        raw = _minimal_overlay_raw()
        raw["patients"][0]["state"] = {
            "enrollments": [{"program": "CCM", "exclusivity_group": "cms_care_management", "status": "ended"}]
        }
        path = _write(tmp_path, "bad-enrollment.yaml", raw)
        with pytest.raises(OverlayError, match=r"bad-enrollment\.yaml"):
            load_overlay(path)

    def test_mid_month_billing_episode_date_is_rejected(self, tmp_path: Path) -> None:
        raw = _minimal_overlay_raw()
        raw["patients"][0]["state"] = {
            "billing_episodes": [
                {
                    "program": "CCM",
                    "exclusivity_group": "cms_care_management",
                    "month": "2026-06-15",
                    "status": "open",
                    "qualification_verdict": "pending",
                }
            ]
        }
        path = _write(tmp_path, "bad-month.yaml", raw)
        with pytest.raises(OverlayError, match=r"bad-month\.yaml") as excinfo:
            load_overlay(path)
        assert "first-of-month" in excinfo.value.reason

    def test_one_bad_file_fails_the_whole_set(self, tmp_path: Path) -> None:
        _write(tmp_path, "good.yaml", _minimal_overlay_raw())
        (tmp_path / "bad.yaml").write_text("format: [unclosed")
        with pytest.raises(OverlayError, match=r"bad\.yaml"):
            load_overlay_set(tmp_path)

    def test_duplicate_patient_across_files_names_both_files(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.yaml", _minimal_overlay_raw())
        _write(tmp_path, "b.yaml", _minimal_overlay_raw(fixture="other_fixture"))
        with pytest.raises(OverlayError, match=r"b\.yaml.*already declared in a\.yaml"):
            load_overlay_set(tmp_path)

    def test_empty_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(OverlayError, match="no overlay files"):
            load_overlay_set(tmp_path)


@pytest.fixture(scope="module")
def applied() -> dict[str, dict[str, Any]]:
    return apply_overlays(_base_population(), load_overlay_set())


class TestNamedFixtures:
    """Each design-doc-named fixture ships, validates, and is present in the applied result."""

    def test_shipped_set_covers_every_named_fixture(self) -> None:
        shipped = {overlay.fixture for overlay in load_overlay_set(DEFAULT_OVERLAY_DIR)}
        assert set(NAMED_FIXTURES) <= shipped

    def test_every_shipped_overlay_names_its_design_doc(self) -> None:
        for overlay in load_overlay_set():
            assert "design/" in overlay.design_ref, f"{overlay.fixture} does not cite a design doc"

    def test_mid_month_exclusivity_switch(self, applied: dict[str, dict[str, Any]]) -> None:
        state = applied["brook-fx-exclusivity-midmonth-0001"]["brook_state"]
        enrollments = state["enrollments"]
        assert [e["status"] for e in enrollments] == ["ended", "active"]
        assert enrollments[0]["end_reason"] == "program_switch"
        assert enrollments[0]["ended_on"] == "2026-06-15"
        assert enrollments[1]["activated_on"] == "2026-06-16"
        episodes = state["billing_episodes"]
        # The double-billing hole: two same-group episodes open for the same month.
        assert len(episodes) == 2
        assert {e["month"] for e in episodes} == {"2026-06-01"}
        assert {e["exclusivity_group"] for e in episodes} == {"cms_care_management"}
        assert {e["program"] for e in episodes} == {"CCM", "PCM"}

    def test_trinary_verdicts_including_indeterminate_with_reason(self, applied: dict[str, dict[str, Any]]) -> None:
        outcomes = {
            pid: record["brook_state"]["verdicts"][0]
            for pid, record in applied.items()
            if record.get("brook_fixture") == "trinary_verdicts" and "verdicts" in record["brook_state"]
        }
        assert {v["outcome"] for v in outcomes.values()} == {"positive", "negative", "indeterminate"}
        indeterminate = outcomes["brook-fx-verdict-indeterminate-0001"]
        assert indeterminate["reason"] == "insufficient_data"
        pending = applied["brook-fx-verdict-pending-0001"]["brook_state"]["billing_episodes"][0]
        assert pending["qualification_verdict"] == "pending"

    def test_genesis_contradiction_set_covers_the_referee_table(self, applied: dict[str, dict[str, Any]]) -> None:
        rows = {
            pid: record["brook_state"]
            for pid, record in applied.items()
            if record.get("brook_fixture") == "genesis_contradictions"
        }
        assert len(rows) == 5
        for state in rows.values():
            assert len(state["source_states"]) >= 2, "a contradiction needs at least two source assertions"
        by_disposition = {pid: state["genesis_expectation"]["disposition"] for pid, state in rows.items()}
        assert by_disposition["brook-fx-genesis-pocar-vs-billy-0001"] == "adjudicated"
        assert by_disposition["brook-fx-genesis-cio-suppression-0001"] == "adjudicated"
        assert by_disposition["brook-fx-genesis-consent-no-evidence-0001"] == "quarantine"
        assert by_disposition["brook-fx-genesis-duplicate-mrn-0001"] == "quarantine"
        assert by_disposition["brook-fx-genesis-uncovered-0001"] == "quarantine"
        cio = rows["brook-fx-genesis-cio-suppression-0001"]["genesis_expectation"]
        assert cio["adjudication_rule"] == "customer_io_wins_unconditionally"
        assert cio["expected_state"] == "suppressed"

    def test_quarantine_bound_consent(self, applied: dict[str, dict[str, Any]]) -> None:
        state = applied["brook-fx-consent-quarantine-0001"]["brook_state"]
        consent = state["consents"][0]
        assert consent["status"] == "granted"
        assert consent["recorded_in"] == "pocar"
        assert "evidence_ref" not in consent, "evidence_ref is engineered absent — that is the fixture"
        expectation = state["genesis_expectation"]
        assert expectation["disposition"] == "quarantine"
        assert expectation["quarantine_reason"] == "consent_without_evidence_ref"


class TestOverlayModel:
    def test_loader_records_the_source_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "example.yaml", _minimal_overlay_raw())
        assert load_overlay(path).source_file == "example.yaml"

    def test_overlay_constructed_in_code_validates_too(self) -> None:
        overlay = Overlay.model_validate(_minimal_overlay_raw())
        assert overlay.fixture == "example_fixture"
        assert overlay.source_file is None
