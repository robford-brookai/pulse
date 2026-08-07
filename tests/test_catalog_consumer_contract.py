"""A downstream consumer resolves the catalog contract from its two pinned surfaces alone.

Covers the `catalog-source` spec scenario "A consumer resolves the contract surfaces": the pin
`docs/contracts/publishes.md` states for `producer-ingress-policy` is `catalog/state_catalog.yaml`
at the repo head plus the programmatic surface `pulse_core.generated` (`CATALOG_VERSION`,
`SUBJECT_TYPES`, `TRANSITIONS`, `COMMAND_TYPES`) — and nothing else. This test acts as that
consumer: it parses the file as plain YAML (no `catalog_gen` loader, no seed, no Snowflake rows,
no generator internals) and asserts the two surfaces agree on the version and the state/command
vocabulary, so a CI gate reading either one gets the same answer.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pulse_core import generated

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_FILE = _REPO_ROOT / "catalog" / "state_catalog.yaml"


def _catalog() -> dict:
    return yaml.safe_load(_CATALOG_FILE.read_text())


class TestAConsumerResolvesTheContractSurfaces:
    def test_both_surfaces_agree_on_catalog_version(self) -> None:
        assert _catalog()["catalog_version"] == generated.CATALOG_VERSION

    def test_both_surfaces_agree_on_the_subject_vocabulary(self) -> None:
        assert set(_catalog()["subjects"]) == generated.SUBJECT_TYPES

    def test_both_surfaces_agree_on_states_and_adjacency(self) -> None:
        file_transitions = {
            subject: {state: frozenset(targets) for state, targets in spec["transitions"].items()}
            for subject, spec in _catalog()["subjects"].items()
        }
        assert file_transitions == generated.TRANSITIONS

    def test_both_surfaces_agree_on_the_command_vocabulary(self) -> None:
        assert set(_catalog()["commands"]) == generated.COMMAND_TYPES
