"""Authoritative catalog tests: the file at `catalog/state_catalog.yaml` loads, malformed ones don't.

Covers `catalog-source` spec scenarios "A schema-valid catalog loads" and "A malformed catalog is
rejected naming the violation". Since task 2.1 this file is the generator's only input — the
Appendix C seed is retired.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pulse_core import catalog_gen
from pydantic import ValidationError

REPO_ROOT = Path(__file__).parents[3]
CATALOG_PATH = REPO_ROOT / "catalog" / "state_catalog.yaml"


@pytest.fixture
def catalog_data() -> dict[str, Any]:
    """The authoritative catalog as raw YAML, for mutation into malformed variants."""
    with CATALOG_PATH.open() as fh:
        return copy.deepcopy(yaml.safe_load(fh))


def test_module_default_path_is_the_authoritative_file() -> None:
    assert catalog_gen.CATALOG_PATH == CATALOG_PATH


def test_authoritative_catalog_loads_into_the_validated_model() -> None:
    catalog = catalog_gen.load_catalog()

    assert catalog.catalog_version == "1.1.0"
    assert catalog.subjects
    assert catalog.commands
    assert catalog.valuesets
    assert catalog.programs


def test_registry_subjects_cover_every_command_subject_without_a_state_machine() -> None:
    catalog = catalog_gen.load_catalog()
    pinned = {spec.subject_type for spec in catalog.commands.values() if spec.subject_type}

    assert "person" in catalog.registry_subjects
    assert pinned - set(catalog.subjects) == set(catalog.registry_subjects)


def test_referral_closure_reasons_are_the_seeded_valueset() -> None:
    catalog = catalog_gen.load_catalog()

    assert set(catalog.valuesets["referral_closure_reason"].codes) == {
        "deceased",
        "duplicate",
        "clinic_terminated",
    }


def test_programs_are_the_d11_set() -> None:
    catalog = catalog_gen.load_catalog()

    assert set(catalog.programs) == {"pcm", "ccm", "rpm", "apcm"}


def test_no_command_binds_a_valueset_at_v1() -> None:
    # v1.0.0 carries the commands over unchanged; the ValueSets exist for D18's catalog rows and
    # the breaking-change rule. Binding is a later catalog PR — see HANDOFF.md.
    catalog = catalog_gen.load_catalog()

    assert all(spec.reason_valueset is None for spec in catalog.commands.values())


# --- "A malformed catalog is rejected naming the violation" -------------------------------------


def test_unknown_top_level_key_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["rulesets"] = {}

    with pytest.raises(ValidationError, match="rulesets"):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_unknown_key_inside_a_valueset_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["valuesets"]["referral_closure_reason"]["binding_strength"] = "required"

    with pytest.raises(ValidationError, match="binding_strength"):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_unknown_key_inside_a_program_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["programs"]["ccm"]["cpt_codes"] = ["99490"]

    with pytest.raises(ValidationError, match="cpt_codes"):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_transition_to_an_undeclared_state_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["subjects"]["referral"]["transitions"]["received"] = ["never_declared"]

    with pytest.raises(ValidationError, match="never_declared"):
        catalog_gen.Catalog.model_validate(catalog_data)


@pytest.mark.parametrize("version", ["appendix-c-v0.7", "1.0", "v1.0.0", "1.0.0-rc1", "01.0.0"])
def test_non_semver_version_is_rejected(catalog_data: dict[str, Any], version: str) -> None:
    catalog_data["catalog_version"] = version

    with pytest.raises(ValidationError, match=version):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_command_referencing_an_undeclared_subject_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["commands"]["resolve_referral"]["subject_type"] = "household"

    with pytest.raises(ValidationError, match="household"):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_command_referencing_an_undeclared_valueset_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["commands"]["declare_transition"]["reason_valueset"] = "closure_reasons_v2"

    with pytest.raises(ValidationError, match="closure_reasons_v2"):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_an_empty_valueset_is_rejected(catalog_data: dict[str, Any]) -> None:
    catalog_data["valuesets"]["referral_closure_reason"]["codes"] = {}

    with pytest.raises(ValidationError, match="referral_closure_reason"):
        catalog_gen.Catalog.model_validate(catalog_data)


def test_a_rejected_catalog_produces_no_partial_model(catalog_data: dict[str, Any], tmp_path: Path) -> None:
    catalog_data["catalog_version"] = "not-semver"
    catalog_data["subjects"]["referral"]["transitions"]["received"] = ["never_declared"]
    broken = tmp_path / "state_catalog.yaml"
    broken.write_text(yaml.safe_dump(catalog_data))
    loaded: catalog_gen.Catalog | None = None

    with pytest.raises(ValidationError) as excinfo:
        loaded = catalog_gen.load_catalog(broken)

    assert loaded is None
    # Every violation is reported, not just the first — a partial catalog is never handed back.
    message = str(excinfo.value)
    assert "not-semver" in message
    assert "never_declared" in message
