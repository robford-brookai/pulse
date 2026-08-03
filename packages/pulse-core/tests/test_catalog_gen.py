"""Generator tests: the committed module is exactly what the seed regenerates, and bad seeds fail."""

from __future__ import annotations

from pathlib import Path

import pytest
from pulse_core import catalog_gen
from pydantic import ValidationError

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "pulse_core"
SEED_PATH = PACKAGE_ROOT / "catalog" / "state_catalog_seed.yaml"
GENERATED_PATH = PACKAGE_ROOT / "generated" / "__init__.py"


def test_committed_module_matches_regeneration() -> None:
    seed = catalog_gen.load_seed(SEED_PATH)
    assert catalog_gen.render_module(seed) == GENERATED_PATH.read_text()


def test_check_mode_passes_on_committed_tree() -> None:
    assert catalog_gen.main(["--check"]) == 0


def test_transition_target_must_be_a_known_state() -> None:
    seed = {
        "catalog_version": "test-v0",
        "subjects": {
            "device": {
                "ownership": "ledger",
                "transitions": {"ordered": ["shipped"], "shipped": []},
            }
        },
        "commands": {},
    }
    seed["subjects"]["device"]["transitions"]["ordered"] = ["never_declared"]
    with pytest.raises(ValidationError, match="never_declared"):
        catalog_gen.Seed.model_validate(seed)


def test_command_field_type_must_be_in_vocabulary() -> None:
    seed = {
        "catalog_version": "test-v0",
        "subjects": {},
        "commands": {"declare_thing": {"fields": {"weight": "float64"}}},
    }
    with pytest.raises(ValidationError):
        catalog_gen.Seed.model_validate(seed)


def test_rendering_is_deterministic() -> None:
    seed = catalog_gen.load_seed(SEED_PATH)
    assert catalog_gen.render_module(seed) == catalog_gen.render_module(seed)
