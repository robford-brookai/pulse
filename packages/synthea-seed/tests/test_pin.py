"""Task 1.1 — pin config validates (spec: Generation is byte-identical and receipted)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from synthea_seed.pin import DEFAULT_PIN_PATH, REQUIRED_PROFILES, PinConfig, load_pin


def _valid_raw() -> dict[str, Any]:
    return {
        "jar": {
            "version": "v3.3.0",
            "url": "https://example.invalid/synthea-with-dependencies.jar",
            "sha256": "a" * 64,
        },
        "seed": 20260809,
        "clinician_seed": 20260809,
        "reference_date": "20260809",
        "properties": {"exporter.fhir.export": "true"},
        "profiles": {
            "dev": {"population": 500, "state": "Massachusetts", "manifest": "manifests/dev.manifest.json"},
            "staging": {"population": 50000, "state": "Massachusetts", "manifest": "manifests/staging.manifest.json"},
        },
    }


class TestCommittedPin:
    def test_packaged_pin_loads_and_validates(self) -> None:
        pin = load_pin()
        assert pin.jar.version == "v3.3.0"
        assert pin.jar.url.startswith("https://github.com/synthetichealth/synthea/releases/download/")

    def test_packaged_pin_defines_both_tier_shapes(self) -> None:
        pin = load_pin(DEFAULT_PIN_PATH)
        assert set(REQUIRED_PROFILES) <= set(pin.profiles)
        # Runtime readiness §2 tier shapes: dev ~500, staging ~50k.
        assert pin.profiles["dev"].population == 500
        assert pin.profiles["staging"].population == 50000
        assert pin.profiles["dev"].manifest != pin.profiles["staging"].manifest

    def test_packaged_pin_keeps_wall_clock_out_of_generation(self) -> None:
        pin = load_pin()
        assert pin.reference_date.isdigit() and len(pin.reference_date) == 8
        assert pin.properties.get("exporter.use_uuid_filenames") == "true"


class TestPinValidation:
    def test_valid_raw_config_validates(self) -> None:
        pin = PinConfig.model_validate(_valid_raw())
        assert pin.profile("dev").population == 500

    def test_malformed_checksum_is_rejected(self) -> None:
        raw = _valid_raw()
        raw["jar"]["sha256"] = "not-a-checksum"
        with pytest.raises(ValidationError):
            PinConfig.model_validate(raw)

    def test_insecure_jar_url_is_rejected(self) -> None:
        raw = _valid_raw()
        raw["jar"]["url"] = "http://example.invalid/synthea.jar"
        with pytest.raises(ValidationError):
            PinConfig.model_validate(raw)

    def test_missing_required_profile_is_rejected(self) -> None:
        raw = _valid_raw()
        del raw["profiles"]["staging"]
        with pytest.raises(ValidationError, match="staging"):
            PinConfig.model_validate(raw)

    def test_nonpositive_population_is_rejected(self) -> None:
        raw = _valid_raw()
        raw["profiles"]["dev"]["population"] = 0
        with pytest.raises(ValidationError):
            PinConfig.model_validate(raw)

    def test_unknown_keys_are_rejected(self) -> None:
        raw = _valid_raw()
        raw["surprise"] = True
        with pytest.raises(ValidationError):
            PinConfig.model_validate(raw)

    def test_unknown_profile_lookup_names_the_pinned_ones(self) -> None:
        pin = PinConfig.model_validate(_valid_raw())
        with pytest.raises(ValueError, match="dev"):
            pin.profile("prod")

    def test_load_pin_from_explicit_path(self, tmp_path: Path) -> None:
        import yaml

        config = tmp_path / "pin.yaml"
        config.write_text(yaml.safe_dump(_valid_raw()))
        assert load_pin(config).seed == 20260809
