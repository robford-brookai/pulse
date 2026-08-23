"""billing-source-boundary task 2.2: the command envelope refuses money, evidence stays opaque.

Offline against the real coercion path in `pulse_ledger.api` — no app, no committer, no database.
`coerce_declaration_fields` runs before any catalog or subject-type awareness exists, so a
monetary field is refused for the same reason any other unknown field is (`UnknownDeclarationFieldError`,
task 3.2's "refused, never silently dropped"): the boundary does not special-case billing, it just
has no place for a field `Declaration` never declared. The complement proves that is the whole
rule — `payload` is a declared field, so whatever a writer puts inside it, including a dollar
figure, passes through untouched. Evidence is opaque to PULSE; state is not (delta requirement
"Money may appear in evidence, never in state").

Synthetic ids throughout; no real payer identifiers.
"""

from __future__ import annotations

import pytest
from pulse_ledger.api import UnknownDeclarationFieldError, coerce_declaration_fields

SUBJECT_KEY = "billing-episode-0001"


def _transition_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_type": "billing_episode",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_transition",
        "to_state": "qualified",
        "effective_at": "2026-08-22T00:00:00+00:00",
    }
    body.update(overrides)
    return body


def _verdict_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_type": "billing_episode",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_verdict",
        "to_state": "qualified",
        "effective_at": "2026-08-22T00:00:00+00:00",
        "rule_version": "appendix-c-v0.7",
    }
    body.update(overrides)
    return body


class TestMonetaryFieldRefusal:
    """A monetary field at the top level has no place in `Declaration` — refused, not dropped."""

    def test_a_transition_carrying_an_allowed_amount_is_refused(self) -> None:
        body = _transition_body(allowed_amount=123.45)
        with pytest.raises(UnknownDeclarationFieldError) as excinfo:
            coerce_declaration_fields(body)
        assert "allowed_amount" in excinfo.value.names

    def test_a_verdict_carrying_a_rate_cents_is_refused(self) -> None:
        body = _verdict_body(rate_cents=4500)
        with pytest.raises(UnknownDeclarationFieldError) as excinfo:
            coerce_declaration_fields(body)
        assert "rate_cents" in excinfo.value.names


class TestEvidenceStaysOpaque:
    """The boundary is state-vs-evidence, not a keyword ban: money inside `payload` is untouched."""

    def test_a_verdict_with_monetary_evidence_in_payload_coerces_cleanly(self) -> None:
        body = _verdict_body(payload={"copay": "35.00", "benefit_category": "QMB"})
        coerced = coerce_declaration_fields(body)
        assert coerced["payload"] == {"copay": "35.00", "benefit_category": "QMB"}
