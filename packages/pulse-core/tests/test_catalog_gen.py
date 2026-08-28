"""Generator tests: the committed module is exactly what the authoritative catalog regenerates.

Covers the `catalog-source` spec scenarios "The generated module derives from the authoritative
catalog" and "The Appendix C seed is retired": the generator reads `catalog/state_catalog.yaml`
as its only input, the committed module is pinned to its `catalog_version`, and the seed file is
absent and unreferenced.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pulse_core import catalog_gen
from pydantic import ValidationError

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "pulse_core"
GENERATED_PATH = PACKAGE_ROOT / "generated" / "__init__.py"


def test_committed_module_matches_regeneration() -> None:
    catalog = catalog_gen.load_catalog()
    assert catalog_gen.render_module(catalog) == GENERATED_PATH.read_text()


def test_check_mode_passes_on_committed_tree() -> None:
    assert catalog_gen.main(["--check"]) == 0


def test_generated_module_is_pinned_to_the_catalog_version() -> None:
    catalog = catalog_gen.load_catalog()
    rendered = catalog_gen.render_module(catalog)

    assert catalog.catalog_version == "1.1.0"
    assert f'CATALOG_VERSION = "{catalog.catalog_version}"' in rendered


def test_generated_provenance_cites_the_authoritative_catalog() -> None:
    rendered = catalog_gen.render_module(catalog_gen.load_catalog())

    assert "catalog/state_catalog.yaml" in rendered
    assert "state_catalog_seed" not in rendered


def test_the_seed_is_retired() -> None:
    # Spec: "the seed file is absent and no code or generator path references it".
    assert not (PACKAGE_ROOT / "catalog" / "state_catalog_seed.yaml").exists()
    assert not (PACKAGE_ROOT / "catalog").exists()
    assert not hasattr(catalog_gen, "SEED_PATH")
    assert not hasattr(catalog_gen, "load_seed")
    assert not hasattr(catalog_gen, "Seed")


def _minimal_catalog() -> dict[str, object]:
    return {
        "catalog_version": "0.0.1",
        "subjects": {},
        "commands": {},
        "valuesets": {},
        "programs": {},
    }


def test_transition_target_must_be_a_known_state() -> None:
    data = _minimal_catalog()
    data["subjects"] = {
        "device": {
            "ownership": "ledger",
            "transitions": {"ordered": ["never_declared"], "shipped": []},
        }
    }
    with pytest.raises(ValidationError, match="never_declared"):
        catalog_gen.Catalog.model_validate(data)


def test_command_field_type_must_be_in_vocabulary() -> None:
    data = _minimal_catalog()
    data["commands"] = {"declare_thing": {"fields": {"weight": "float64"}}}
    with pytest.raises(ValidationError):
        catalog_gen.Catalog.model_validate(data)


def test_rendering_is_deterministic() -> None:
    catalog = catalog_gen.load_catalog()
    assert catalog_gen.render_module(catalog) == catalog_gen.render_module(catalog)
