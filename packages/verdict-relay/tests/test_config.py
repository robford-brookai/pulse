"""`verdict_relay.config` — the shipped verdict-type configuration (task 2.2, billing-state).

This module is the sole owner of the shipped entries: `SUBJECT_TYPE_BY_VERDICT` and
`TRANSITION_BY_OUTCOME` for `billing_eligibility` (→ `billing_episode`), `coverage_eligibility`
and `benefits_verification` (→ `coverage`). Pins here keep the shipped entries catalog-legal,
cover the verdict-declare scenario "A positive billing-eligibility verdict qualifies the
episode", and regression-pin that an unmapped verdict type still fails before any API call.

The command API is faked at the client boundary (`httpx.MockTransport` under a real
`PulseCoreClient`); `conftest.py` blocks sockets for every run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from pulse_core.generated import SUBJECT_TYPES, TRANSITIONS
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT, TRANSITION_BY_OUTCOME
from verdict_relay.declarer import Declarer, RowValidationError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def mart_row(**overrides: object) -> dict[str, object]:
    """One synthetic mart-contract row; keyword overrides mutate nothing shared."""
    row: dict[str, object] = {
        "subject_id": "episode-2001",
        "verdict_type": "billing_eligibility",
        "outcome": "positive",
        "reason": None,
        "rule_version": "rules-v3",
        "as_of": "2026-08-01T00:00:00+00:00",
        "lineage_ref": "dbt-run-2026-08-01T02",
        "computed_at": "2026-08-01T02:00:00+00:00",
    }
    row.update(overrides)
    return row


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


class ScriptedApi:
    """The command API faked at the client boundary; the last scripted response repeats."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        assert self._responses, "no API call should occur in this test"
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


def shipped_declarer(api: ScriptedApi) -> Declarer:
    """A declarer running exactly the shipped configuration — nothing synthetic mixed in."""
    return Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        transition_by_outcome=TRANSITION_BY_OUTCOME,
        sleep=lambda _s: None,
        jitter=lambda: 0.0,
    )


class TestShippedEntries:
    """The shipped entries are exactly the three the change registers, catalog-legal."""

    def test_the_subject_type_entries_are_exactly_the_three_registered_types(self) -> None:
        assert dict(SUBJECT_TYPE_BY_VERDICT) == {
            "billing_eligibility": "billing_episode",
            "coverage_eligibility": "coverage",
            "benefits_verification": "coverage",
        }

    def test_the_transition_entries_map_the_registered_types_and_no_others(self) -> None:
        assert {k: dict(v) for k, v in TRANSITION_BY_OUTCOME.items()} == {
            "billing_eligibility": {"positive": "qualified", "negative": "not_qualified"},
            "coverage_eligibility": {"positive": "verified_active", "negative": "verified_inactive"},
            "benefits_verification": {"positive": "verified_active", "negative": "verified_inactive"},
        }

    def test_every_transition_entry_has_a_subject_type_entry(self) -> None:
        assert set(TRANSITION_BY_OUTCOME) <= set(SUBJECT_TYPE_BY_VERDICT)

    def test_every_mapped_subject_type_is_a_catalog_subject(self) -> None:
        assert set(SUBJECT_TYPE_BY_VERDICT.values()) <= SUBJECT_TYPES

    def test_every_mapped_to_state_is_in_its_subjects_catalog_vocabulary(self) -> None:
        for verdict_type, by_outcome in TRANSITION_BY_OUTCOME.items():
            subject_type = SUBJECT_TYPE_BY_VERDICT[verdict_type]
            for to_state in by_outcome.values():
                assert to_state in TRANSITIONS[subject_type], (
                    f"{verdict_type} maps to {to_state!r}, not a {subject_type} state"
                )

    def test_indeterminate_never_maps_to_a_transition(self) -> None:
        # An indeterminate verdict is evidence without consequence: verdict only, no transition.
        for by_outcome in TRANSITION_BY_OUTCOME.values():
            assert set(by_outcome) <= {"positive", "negative"}

    def test_the_shipped_mappings_are_immutable(self) -> None:
        with pytest.raises(TypeError):
            SUBJECT_TYPE_BY_VERDICT["rogue"] = "billing_episode"  # type: ignore[index]
        with pytest.raises(TypeError):
            TRANSITION_BY_OUTCOME["billing_eligibility"]["positive"] = "reported"  # type: ignore[index]


class TestBillingEligibilityScenario:
    """Scenario: a positive billing-eligibility verdict qualifies the episode."""

    def test_a_positive_row_commits_the_verdict_and_one_paired_transition_to_qualified(self) -> None:
        api = ScriptedApi([committed("e1"), committed("e2")])
        declarer = shipped_declarer(api)

        declarer.declare(mart_row())

        assert declarer.counts.declared == 1
        assert declarer.counts.transitioned == 1
        verdict_body, transition_body = api.bodies
        assert verdict_body["event_type"] == "declare_verdict"
        assert verdict_body["subject_type"] == "billing_episode"
        assert transition_body["event_type"] == "declare_transition"
        assert transition_body["subject_type"] == "billing_episode"
        assert transition_body["subject_key"] == "episode-2001"
        assert transition_body["to_state"] == "qualified"

    def test_both_halves_are_attributed_to_the_relays_identity(self) -> None:
        api = ScriptedApi([committed("e1"), committed("e2")])
        declarer = shipped_declarer(api)

        declarer.declare(mart_row())

        for body in api.bodies:
            # Attribution is the relay's service credential, applied server-side (D15): the
            # D16 key carries the writer id and the body names no actor.
            key = body["idempotency_key"]
            assert isinstance(key, str)
            assert key.startswith("verdict-relay:")
            assert not any(field.startswith("actor") for field in body)

    def test_a_negative_row_pairs_a_transition_to_not_qualified(self) -> None:
        api = ScriptedApi([committed("e1"), committed("e2")])
        shipped_declarer(api).declare(mart_row(outcome="negative"))
        assert api.bodies[1]["to_state"] == "not_qualified"


class TestCoverageEntries:
    """Both coverage verdict types pair onto the `coverage` subject."""

    @pytest.mark.parametrize("verdict_type", ["coverage_eligibility", "benefits_verification"])
    def test_a_positive_row_pairs_a_transition_to_verified_active(self, verdict_type: str) -> None:
        api = ScriptedApi([committed("e1"), committed("e2")])
        declarer = shipped_declarer(api)

        declarer.declare(mart_row(subject_id="coverage-3001", verdict_type=verdict_type))

        assert declarer.counts.transitioned == 1
        verdict_body, transition_body = api.bodies
        assert verdict_body["subject_type"] == "coverage"
        assert transition_body["subject_type"] == "coverage"
        assert transition_body["to_state"] == "verified_active"

    @pytest.mark.parametrize("verdict_type", ["coverage_eligibility", "benefits_verification"])
    def test_a_negative_row_pairs_a_transition_to_verified_inactive(self, verdict_type: str) -> None:
        api = ScriptedApi([committed("e1"), committed("e2")])
        shipped_declarer(api).declare(
            mart_row(subject_id="coverage-3001", verdict_type=verdict_type, outcome="negative")
        )
        assert api.bodies[1]["to_state"] == "verified_inactive"

    @pytest.mark.parametrize("verdict_type", ["coverage_eligibility", "benefits_verification"])
    def test_an_indeterminate_row_submits_the_verdict_only(self, verdict_type: str) -> None:
        api = ScriptedApi([committed("e1")])
        declarer = shipped_declarer(api)
        declarer.declare(
            mart_row(
                subject_id="coverage-3001",
                verdict_type=verdict_type,
                outcome="indeterminate",
                reason="271 response ambiguous",
            )
        )
        assert len(api.bodies) == 1
        assert declarer.counts.transitioned == 0


class TestUnmappedTypeRegressionPin:
    """Regression pin: an unmapped verdict type still fails before any API call."""

    def test_an_unmapped_type_fails_validation_with_zero_api_calls(self) -> None:
        api = ScriptedApi([])  # any submission fails loudly
        declarer = shipped_declarer(api)

        with pytest.raises(RowValidationError) as excinfo:
            declarer.declare(mart_row(verdict_type="marketing_clearance"))

        assert api.bodies == []
        assert "marketing_clearance" in str(excinfo.value)
        assert "episode-2001" in str(excinfo.value)  # named by its keys only


class TestFixtureCorpusIsSynthetic:
    """Every fixture corpus row carries synthetic identifiers only (no-PHI posture)."""

    #: Synthetic-by-construction shapes: catalog-subject prefixes and dbt-run lineage refs.
    SYNTHETIC_SUBJECT_ID = re.compile(r"^(episode|coverage)-\d+$")
    SYNTHETIC_LINEAGE_REF = re.compile(r"^dbt-run-[0-9T:-]+$")

    def all_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for path in sorted(FIXTURES_DIR.glob("*.json")):
            recorded: object = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(recorded, dict)
            rows.extend(cast("list[dict[str, object]]", recorded["rows"]))
        return rows

    def test_the_corpus_carries_rows_for_all_three_shipped_verdict_types(self) -> None:
        recorded_types = {row["verdict_type"] for row in self.all_rows()}
        assert set(SUBJECT_TYPE_BY_VERDICT) <= recorded_types

    def test_every_fixture_row_carries_synthetic_identifiers_only(self) -> None:
        for row in self.all_rows():
            assert self.SYNTHETIC_SUBJECT_ID.match(str(row["subject_id"])), row["subject_id"]
            assert self.SYNTHETIC_LINEAGE_REF.match(str(row["lineage_ref"])), row["lineage_ref"]
