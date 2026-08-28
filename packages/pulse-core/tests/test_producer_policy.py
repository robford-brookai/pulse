"""The §4.4 producer-policy classifier: subject-scoped matching over producer source.

Covers the `producer-policy` spec scenarios "A state-asserting producer schema is flagged", "A
non-subject fact schema passes", and "A bare-word name collision does not flag", plus the
G_MECE narrowing of design decision 3 — a subject-prefixed event type whose action word is not
a state of that subject (`device.associated`) never flags, while a planted `enrollment.active`
does. The suppressions section (producer-ingress-policy 2.1) covers "A justified suppression
suppresses exactly the named finding" and "A stale or unjustified suppression fails the gate".

Fixtures are synthetic producer sources parsed as text. Nothing here imports scanned code, and
the one test that reads a committed file (ocean's real `types.py`) reads it as source.
"""

from __future__ import annotations

from pathlib import Path

from pulse_core.generated import TRANSITIONS
from pulse_core.producer_policy import (
    DISPOSITION,
    Finding,
    SuppressionError,
    apply_suppressions,
    classify_files,
    classify_source,
    parse_suppressions,
    render_report,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# --- A state-asserting producer schema is flagged -----------------------------------------


REFERRAL_SCHEMA = '''
"""A planted producer schema that asserts referral state."""

from typing import Literal

ReferralStatus = Literal["screened", "outreach", "converted"]
'''


def test_state_vocabulary_naming_a_subject_state_set_is_flagged() -> None:
    findings = classify_source("libs/ocean-events/src/ocean_events/planted.py", REFERRAL_SCHEMA)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.file == "libs/ocean-events/src/ocean_events/planted.py"
    assert finding.element == "ReferralStatus"
    assert finding.subject == "referral"
    assert finding.states == ("converted", "outreach", "screened")


def test_an_enum_state_vocabulary_is_flagged() -> None:
    source = """
from enum import Enum


class ReferralOutcome(str, Enum):
    SCREENED = "screened"
    CONVERTED = "converted"
"""
    findings = classify_source("producer.py", source)

    assert [(f.element, f.subject, f.states) for f in findings] == [
        ("ReferralOutcome", "referral", ("converted", "screened")),
    ]


def test_a_frozen_string_set_constant_is_flagged() -> None:
    source = 'ENROLLMENT_STATES = frozenset({"active", "on_hold"})\n'
    findings = classify_source("producer.py", source)

    assert [(f.element, f.subject, f.states) for f in findings] == [
        ("ENROLLMENT_STATES", "enrollment", ("active", "on_hold")),
    ]


def test_an_entity_type_equal_to_a_catalog_subject_is_flagged() -> None:
    source = """
def emit_referral(bus, referral_id):
    bus.publish(entity_type="referral", entity_id=referral_id)
"""
    findings = classify_source("services/api/src/emit.py", source)

    assert [(f.element, f.subject, f.states) for f in findings] == [
        ("emit_referral.entity_type", "referral", ()),
    ]


def test_an_event_type_naming_a_state_of_its_subject_prefix_is_flagged() -> None:
    source = 'EVENT = None\n\n\ndef emit(bus):\n    bus.publish(event_type="enrollment.active")\n'
    findings = classify_source("services/api/src/emit.py", source)

    assert [(f.element, f.subject, f.states) for f in findings] == [
        ("emit.event_type", "enrollment", ("active",)),
    ]


def test_an_event_type_whose_state_rides_in_the_payload_is_flagged() -> None:
    source = """
def emit(bus):
    bus.publish(event_type="enrollment.updated", payload={"status": "on_hold"})
"""
    findings = classify_source("services/api/src/emit.py", source)

    assert [(f.element, f.subject, f.states) for f in findings] == [
        ("emit.event_type", "enrollment", ("on_hold",)),
    ]


def test_a_state_asserting_class_attribute_is_flagged() -> None:
    source = """
from typing import Literal

from ocean_events.base import BaseEvent


class ReferralScreened(BaseEvent):
    event_type: Literal["referral.screened"] = "referral.screened"
"""
    findings = classify_source("producer.py", source)

    assert [(f.element, f.subject, f.states) for f in findings] == [
        ("ReferralScreened.event_type", "referral", ("screened",)),
    ]


# --- A non-subject fact schema passes ------------------------------------------------------


FACT_SCHEMA = '''
"""Non-subject facts: a reading landed, a call completed, a document arrived."""

from typing import Literal

SignalKind = Literal["weight", "blood_pressure", "glucose"]
CallOutcome = Literal["connected", "missed", "voicemail"]
DOCUMENT_KINDS = frozenset({"referral_form", "consent_form"})


def emit_reading(bus, reading_id):
    bus.publish(event_type="signal.received", entity_type="signal", entity_id=reading_id)
'''


def test_a_non_subject_fact_schema_yields_no_finding() -> None:
    assert classify_source("libs/ocean-events/src/ocean_events/facts.py", FACT_SCHEMA) == []


# --- A bare-word name collision does not flag ----------------------------------------------


COLLISION_SCHEMA = """
from typing import Literal

AlertStatus = Literal["open", "claimed", "resolved", "dismissed"]
TicketStatus = Literal["open", "in_progress", "waiting", "resolved"]
"""


def test_bare_word_collision_vocabularies_yield_no_finding() -> None:
    assert classify_source("libs/ocean-events/src/ocean_events/types.py", COLLISION_SCHEMA) == []


def test_a_single_bare_word_never_flags() -> None:
    source = 'ContractState = Literal["active"]\nSTATUS = "active"\n'
    assert classify_source("producer.py", source) == []


def test_a_vocabulary_subset_of_two_subjects_is_ambiguous_and_does_not_flag() -> None:
    # A vocabulary that fits two subjects identifies neither, so it stays green rather than
    # guessing. No pair of catalog subjects shares two states today, so the rule is pinned
    # against an injected catalog rather than a coincidence of the current one.
    transitions = {
        "left": {"active": frozenset(), "ended": frozenset(), "only_left": frozenset()},
        "right": {"active": frozenset(), "ended": frozenset(), "only_right": frozenset()},
    }
    source = 'BOTH = Literal["active", "ended"]\nONE = Literal["active", "only_left"]\n'

    findings = classify_source("producer.py", source, transitions=transitions)

    assert [(f.element, f.subject) for f in findings] == [("ONE", "left")]


def test_a_subject_prefixed_event_type_with_a_non_state_action_does_not_flag() -> None:
    # The G_MECE narrowing: ocean's real device.associated shares the `device` prefix, but
    # `associated` is not a device state (ordered/shipped/delivered/active/returned/lost).
    source = """
from typing import Literal

EventType = Literal["device.associated", "device.disassociated", "contract.signed"]
"""
    assert classify_source("libs/ocean-events/src/ocean_events/types.py", source) == []


def test_an_entity_type_merely_containing_a_subject_name_does_not_flag() -> None:
    source = 'EntityType = Literal["device_association", "patient", "alert"]\n'
    assert classify_source("producer.py", source) == []


def test_the_committed_ocean_event_vocabulary_is_green() -> None:
    types_py = REPO_ROOT / "packages/ocean/libs/ocean-events/src/ocean_events/types.py"

    assert classify_files([types_py], root=REPO_ROOT) == []


# --- The classifier is pure and deterministic ----------------------------------------------


def test_classification_is_deterministic_and_sorted() -> None:
    source = 'B = Literal["screened", "outreach"]\nA = frozenset({"active", "on_hold"})\n'
    findings = classify_source("producer.py", source)

    assert [f.element for f in findings] == ["A", "B"]
    assert findings == classify_source("producer.py", source)


def test_syntactically_invalid_source_yields_no_finding() -> None:
    assert classify_source("broken.py", "def (: \n") == []


def test_classification_reads_the_catalog_it_is_handed() -> None:
    transitions = {"widget": {"spinning": frozenset({"stopped"}), "stopped": frozenset()}}
    source = 'WidgetState = Literal["spinning", "stopped"]\nReferralState = Literal["screened", "outreach"]\n'

    findings = classify_source("producer.py", source, transitions=transitions)

    assert [(f.element, f.subject) for f in findings] == [("WidgetState", "widget")]


def test_classify_files_reads_only_the_files_it_is_handed(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(REFERRAL_SCHEMA, encoding="utf-8")
    (tmp_path / "unseen.py").write_text(REFERRAL_SCHEMA, encoding="utf-8")

    findings = classify_files([planted], root=tmp_path)

    assert [(f.file, f.element) for f in findings] == [("planted.py", "ReferralStatus")]


# --- A red gate names the §4.4 disposition -------------------------------------------------


def test_a_finding_renders_file_element_subject_and_states() -> None:
    finding = Finding(file="producer.py", element="ReferralStatus", subject="referral", states=("outreach", "screened"))

    assert finding.render() == "producer.py:ReferralStatus asserts referral state(s) outreach, screened"


def test_a_subject_addressing_finding_without_states_renders_the_subject() -> None:
    finding = Finding(file="emit.py", element="emit.entity_type", subject="referral", states=())

    assert finding.render() == "emit.py:emit.entity_type declares catalog subject referral"


def test_the_report_carries_every_finding_and_the_fixed_disposition_line() -> None:
    findings = classify_source("producer.py", REFERRAL_SCHEMA)

    report = render_report(findings)

    assert "producer.py:ReferralStatus asserts referral state(s) converted, outreach, screened" in report
    assert DISPOSITION in report
    assert "pulse_core.submit_command" in DISPOSITION
    assert "producer-policy-suppressions.yaml" in DISPOSITION


def test_an_empty_report_states_the_tree_is_green() -> None:
    assert render_report([]) == "No producer-policy findings."


# --- The pinned contract surface -----------------------------------------------------------


def test_the_default_catalog_is_the_pinned_generated_surface() -> None:
    # The classifier's default matcher is TRANSITIONS, not the seed or a Snowflake read.
    source = 'ReferralState = Literal["screened", "outreach"]\n'
    assert classify_source("p.py", source) == classify_source("p.py", source, transitions=TRANSITIONS)


# --- Suppressions: adjudicated false positives, never exemptions ---------------------------

FINDING_A = Finding(file="libs/x/src/x/types.py", element="AlertStatus", subject="alert", states=("open", "resolved"))
FINDING_B = Finding(
    file="services/y/src/y/emit.py", element="emit.event_type", subject="referral", states=("screened",)
)

JUSTIFIED_SUPPRESSION_DOC = """
suppressions:
  - file: libs/x/src/x/types.py
    element: AlertStatus
    subject: alert
    justification: "adjudicated false positive: AlertStatus collides with catalog state words only"
"""

UNJUSTIFIED_SUPPRESSION_DOC = """
suppressions:
  - file: libs/x/src/x/types.py
    element: AlertStatus
    subject: alert
"""

STALE_SUPPRESSION_DOC = """
suppressions:
  - file: libs/x/src/x/types.py
    element: NeverFound
    subject: alert
    justification: "adjudicated false positive"
"""


def test_a_justified_suppression_suppresses_exactly_the_named_finding() -> None:
    # spec: "A justified suppression suppresses exactly the named finding"
    entries = parse_suppressions(JUSTIFIED_SUPPRESSION_DOC)

    surviving, errors = apply_suppressions([FINDING_A, FINDING_B], entries)

    assert surviving == [FINDING_B]
    assert errors == []


def test_an_unjustified_entry_fails_the_gate_naming_it() -> None:
    # spec: "A stale or unjustified suppression fails the gate"
    entries = parse_suppressions(UNJUSTIFIED_SUPPRESSION_DOC)

    surviving, errors = apply_suppressions([FINDING_A, FINDING_B], entries)

    assert surviving == [FINDING_A, FINDING_B]
    assert errors == [
        SuppressionError(
            file="libs/x/src/x/types.py", element="AlertStatus", subject="alert", reason="missing justification"
        )
    ]


def test_a_stale_entry_fails_the_gate_naming_it() -> None:
    # spec: "A stale or unjustified suppression fails the gate"
    entries = parse_suppressions(STALE_SUPPRESSION_DOC)

    surviving, errors = apply_suppressions([FINDING_A, FINDING_B], entries)

    assert surviving == [FINDING_A, FINDING_B]
    assert errors == [
        SuppressionError(
            file="libs/x/src/x/types.py",
            element="NeverFound",
            subject="alert",
            reason="matches no current finding",
        )
    ]


def test_an_unrelated_finding_survives_a_justified_suppression_of_another() -> None:
    entries = parse_suppressions(JUSTIFIED_SUPPRESSION_DOC)

    surviving, _errors = apply_suppressions([FINDING_A, FINDING_B], entries)

    assert FINDING_B in surviving


def test_an_empty_suppression_document_parses_to_no_entries() -> None:
    assert parse_suppressions("") == []
    assert parse_suppressions("suppressions: []\n") == []


def test_the_shipped_ocean_suppression_file_is_empty() -> None:
    suppressions_path = REPO_ROOT / "packages/ocean/producer-policy-suppressions.yaml"

    entries = parse_suppressions(suppressions_path.read_text(encoding="utf-8"))

    assert entries == []


def test_a_suppression_error_renders_the_offending_entry() -> None:
    error = SuppressionError(file="p.py", element="X", subject="referral", reason="missing justification")

    assert error.render() == "p.py:X (referral): missing justification"


def test_suppression_entries_and_errors_are_orderable() -> None:
    entries = parse_suppressions(JUSTIFIED_SUPPRESSION_DOC)
    assert entries == sorted(entries)

    _surviving, errors = apply_suppressions([FINDING_A], parse_suppressions(UNJUSTIFIED_SUPPRESSION_DOC))
    assert errors == sorted(errors)
