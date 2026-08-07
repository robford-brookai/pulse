"""Spec tests for the generated command surface (pulse-ledger-core §command-api).

Scenarios covered, from `openspec/changes/pulse-ledger-core/specs/command-api/spec.md`:
- generated adjacency round-trips the authoritative catalog
- unknown command type is absent from the generated vocabulary
- indeterminate verdict without a reason fails model validation
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

import pytest
import yaml
from pulse_core import generated
from pulse_core.generated import (
    BACKFILL_ONLY_COMMAND_TYPES,
    CATALOG_VERSION,
    COMMAND_TYPES,
    TRANSITIONS,
    DeclareVerdictCommand,
    VerdictOutcome,
    parse_command,
)
from pydantic import ValidationError

CATALOG_PATH = Path(__file__).parents[3] / "catalog" / "state_catalog.yaml"


def _load_catalog() -> dict[str, object]:
    with CATALOG_PATH.open() as fh:
        loaded: dict[str, object] = yaml.safe_load(fh)
    return loaded


class TestAdjacencyRoundTripsCatalog:
    def test_catalog_version_matches_catalog(self) -> None:
        assert _load_catalog()["catalog_version"] == CATALOG_VERSION

    def test_every_catalog_transition_is_generated_and_nothing_more(self) -> None:
        catalog_subjects = _load_catalog()["subjects"]
        assert isinstance(catalog_subjects, dict)
        expected = {
            subject: {state: frozenset(targets) for state, targets in spec["transitions"].items()}
            for subject, spec in catalog_subjects.items()
        }
        assert expected == TRANSITIONS

    def test_billing_episode_reentry_loop_is_legal_until_reported(self) -> None:
        billing = TRANSITIONS["billing_episode"]
        assert "not_qualified" in billing["qualified"]
        assert "qualified" in billing["not_qualified"]
        # `reported` freezes the verdict: no path back into the loop.
        assert billing["reported"] == frozenset({"closed"})

    def test_terminal_states_have_no_outgoing_transitions(self) -> None:
        assert TRANSITIONS["enrollment"]["ended"] == frozenset()
        assert TRANSITIONS["referral"]["converted"] == frozenset()


class TestCommandVocabulary:
    SPEC_NAMED_COMMANDS: ClassVar[frozenset[str]] = frozenset({
        "declare_verdict",
        "open_billing_episode",
        "record_communication_consent",
        "resolve_referral",
        "mint_person",
        "attach_identifier",
        "merge_person",
    })

    def test_spec_named_commands_are_generated(self) -> None:
        assert self.SPEC_NAMED_COMMANDS <= COMMAND_TYPES

    def test_unknown_command_type_is_absent(self) -> None:
        assert "close_referral" not in COMMAND_TYPES
        assert not hasattr(generated, "CloseReferralCommand")

    def test_unknown_command_type_fails_parse(self) -> None:
        with pytest.raises(ValidationError):
            parse_command({"command_type": "close_referral", "subject_key": "ref-1"})

    def test_backfill_vocabulary_is_marked_and_generated(self) -> None:
        assert frozenset({"backfill_genesis", "reconstruction_gap"}) == BACKFILL_ONLY_COMMAND_TYPES
        assert BACKFILL_ONLY_COMMAND_TYPES <= COMMAND_TYPES


class TestVerdictModel:
    def test_outcomes_are_trinary(self) -> None:
        assert {outcome.value for outcome in VerdictOutcome} == {"positive", "negative", "indeterminate"}

    def test_indeterminate_without_reason_fails_validation(self) -> None:
        with pytest.raises(ValidationError, match="reason"):
            DeclareVerdictCommand(
                subject_type="billing_episode",
                subject_key="be-2026-06-p1",
                outcome=VerdictOutcome.INDETERMINATE,
                rule_version=CATALOG_VERSION,
                as_of=datetime(2026, 6, 28, tzinfo=timezone.utc),
            )

    def test_indeterminate_with_reason_validates(self) -> None:
        command = DeclareVerdictCommand(
            subject_type="billing_episode",
            subject_key="be-2026-06-p1",
            outcome=VerdictOutcome.INDETERMINATE,
            reason="insufficient_reading_days_data",
            rule_version=CATALOG_VERSION,
            as_of=datetime(2026, 6, 28, tzinfo=timezone.utc),
        )
        assert command.outcome is VerdictOutcome.INDETERMINATE

    def test_determinate_outcome_needs_no_reason(self) -> None:
        command = parse_command({
            "command_type": "declare_verdict",
            "subject_type": "billing_episode",
            "subject_key": "be-2026-06-p1",
            "outcome": "positive",
            "rule_version": CATALOG_VERSION,
            "as_of": "2026-06-28T00:00:00Z",
        })
        assert isinstance(command, DeclareVerdictCommand)
        assert command.reason is None
