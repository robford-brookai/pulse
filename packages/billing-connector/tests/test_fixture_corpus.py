"""Fixture corpus skeleton — one recording per delta-spec scenario (task 1.4).

`tests/fixtures/` holds one JSON stub per `#### Scenario:` heading in
`openspec/changes/billing-connector/specs/billing-connector/spec.md`, named for the scenario it
covers: a fact snapshot in (`facts`/`event`, `null` where the scenario has none), an `expected`
shape out (evaluation and receipt counts, plus scenario-specific assertions). `evaluate.py`,
`declare.py`, and `service.py` still raise `NotImplementedError` at this task — wave 1 fills in
the module bodies and wires each fixture through the real path (verdict-relay's
`test_fixture_corpus.py` pattern); this test proves the corpus itself is complete and each
recording is shaped consistently, ahead of that.

`receipt_shape_is_stable` is the one recording already exercisable end to end: `receipts.py` is
this scaffold task's one implemented module (task 1.3), so its fixture replays through the real
`Receipt.format_line()` here rather than waiting for wave 1.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pytest
from billing_connector.receipts import Receipt

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SPEC_PATH = (
    Path(__file__).resolve().parents[3]
    / "openspec"
    / "changes"
    / "billing-connector"
    / "specs"
    / "billing-connector"
    / "spec.md"
)
_SCENARIO_HEADING = re.compile(r"^#### Scenario: (.+)$", re.MULTILINE)

#: Common counted fields every recording's `expected` block carries, whether or not the
#: scenario actually evaluates or declares anything (a config- or receipt-shape scenario still
#: names all five as zero) — so no fixture can silently omit the shape a later replay test reads.
_COMMON_EXPECTED_COUNTS = ("evaluated", "deferred", "committed", "replayed", "rejected")


def _spec_scenario_titles() -> list[str]:
    return _SCENARIO_HEADING.findall(_SPEC_PATH.read_text())


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


def _load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        recorded: object = json.load(handle)
    assert isinstance(recorded, dict)
    return cast("dict[str, object]", recorded)


class TestCorpusCoversEveryScenario:
    def test_the_spec_has_scenarios_to_check(self) -> None:
        assert _spec_scenario_titles(), "no #### Scenario headings found — spec path is stale"

    def test_every_scenario_has_exactly_one_fixture_file(self) -> None:
        recorded_scenarios = sorted(cast("str", _load(path)["scenario"]) for path in _fixture_paths())
        assert recorded_scenarios == sorted(_spec_scenario_titles())

    def test_every_fixture_file_names_a_case_matching_its_own_filename(self) -> None:
        for path in _fixture_paths():
            recording = _load(path)
            assert recording["case"] == path.stem, f"{path.name} case field does not match its filename"


class TestEveryRecordingIsShapedConsistently:
    @pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
    def test_the_recording_carries_the_required_top_level_keys(self, path: Path) -> None:
        recording = _load(path)
        assert {"case", "scenario", "description", "facts", "event", "expected"} <= set(recording)
        assert recording["description"], f"{path.name} has no description"

    @pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
    def test_the_expected_block_carries_the_common_counts_as_non_negative_ints(self, path: Path) -> None:
        expected = _load(path)["expected"]
        assert isinstance(expected, dict)
        for field in _COMMON_EXPECTED_COUNTS:
            assert field in expected, f"{path.name} expected block is missing {field!r}"
            value = expected[field]
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{path.name} expected[{field!r}] is not an int"
            )
            assert value >= 0, f"{path.name} expected[{field!r}] is negative"


class TestReceiptShapeRecordingReplaysForReal:
    """The one recording this scaffold task can already exercise against real behavior."""

    def test_the_golden_line_matches_receipts_format_line(self) -> None:
        recording = _load(FIXTURES_DIR / "receipt_shape_is_stable.json")
        receipt_fields = recording["receipt"]
        assert isinstance(receipt_fields, dict)
        receipt = Receipt(
            committed=cast("int", receipt_fields["committed"]),
            replayed=cast("int", receipt_fields["replayed"]),
            rejected=cast("int", receipt_fields["rejected"]),
            evaluated=cast("int", receipt_fields["evaluated"]),
            deferred=cast("int", receipt_fields["deferred"]),
        )

        expected = recording["expected"]
        assert isinstance(expected, dict)
        assert receipt.format_line() == expected["line"]
