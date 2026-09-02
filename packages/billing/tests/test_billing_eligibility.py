"""Unit suite for the ported `billing_eligibility` rules (connector-pattern task 3.3).

Every test function here is a named counterpart of a dbt test in
`packages/billing/docs/rule-port-map.md` — `tests/test_rule_port_lineage.py` fails if a mapped
name stops existing. Synthetic subjects only; the rules are pure, so no fixtures, no I/O.
"""

from __future__ import annotations

from datetime import date

import pytest
from billing.rules import billing_eligibility as rules


class TestRuleVersion:
    def test_rule_version_is_the_engine_namespace(self) -> None:
        """The engine's verdicts are attributable to this implementation, never the mart's
        (spec: "A verdict names its implementation")."""
        assert rules.RULE_VERSION == "pulse-billing-eligibility-v1"

    def test_verdict_type_and_subject_are_the_registered_pair(self) -> None:
        """`tests/test_rule_port_lineage.py` cross-checks these two against
        `verdict_relay.config.SUBJECT_TYPE_BY_VERDICT`, the registered vocabulary."""
        assert rules.VERDICT_TYPE == "billing_eligibility"
        assert rules.SUBJECT_TYPE == "billing_episode"


class TestConsentGate:
    """Ports `billing_result_stage_3`'s consent gate:
    `IFF(achieved = TRUE AND consent_start < period_end, TRUE, FALSE)`."""

    def test_consent_start_after_period_end_gates_false(self) -> None:
        """dbt `assert_consent_gates_achievement`: an achieved row whose consent starts on or
        after `period_end` is a violation, so the gate must clear it."""
        assert (
            rules.gate_by_consent(
                achieved=True,
                consent_start=date(2026, 10, 5),
                period_end=date(2026, 9, 30),
            )
            is False
        )

    def test_consent_start_equal_to_period_end_gates_false(self) -> None:
        """Boundary of the same dbt predicate: `>=` is the violation, so `<` is strict."""
        assert (
            rules.gate_by_consent(
                achieved=True,
                consent_start=date(2026, 9, 30),
                period_end=date(2026, 9, 30),
            )
            is False
        )

    def test_late_consent_not_achieved(self) -> None:
        """dbt `assert_consent_after_period_not_achieved` (UC-7.1): consent on Oct 5 against a
        period ending Sep 30 yields achieved = FALSE."""
        assert (
            rules.gate_by_consent(
                achieved=True,
                consent_start=date(2026, 10, 5),
                period_end=date(2026, 9, 30),
            )
            is False
        )

    def test_early_consent_achieved(self) -> None:
        """dbt `assert_consent_before_period_achieved` (UC-7.2): consent on Jan 1 against a
        period ending Sep 30 leaves achievement standing."""
        assert (
            rules.gate_by_consent(
                achieved=True,
                consent_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
            )
            is True
        )

    def test_missing_consent_gates_false(self) -> None:
        """`consent_start IS NULL` makes the SQL predicate NULL, and `IFF(NULL, ...)` is FALSE:
        no consent on record is not a pass."""
        assert rules.gate_by_consent(achieved=True, consent_start=None, period_end=date(2026, 9, 30)) is False

    def test_unachieved_stays_unachieved_under_valid_consent(self) -> None:
        """The gate only ever removes achievement — it never confers it."""
        assert (
            rules.gate_by_consent(
                achieved=False,
                consent_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
            )
            is False
        )

    def test_gates_evaluate_independently_per_program(self) -> None:
        """dbt `assert_protocol_change_independent` (UC-7.5), ported half: each program's gate
        reads that program's own consent, so an RPM consent from Jan 1 stands while a PCM/CCM
        consent from Sep 10 is judged on its own date. Code-level achievement inputs stay
        mart-side; only the independence property ports."""
        period_end = date(2026, 9, 30)
        rpm = rules.gate_by_consent(achieved=True, consent_start=date(2026, 1, 1), period_end=period_end)
        pcm_ccm = rules.gate_by_consent(achieved=True, consent_start=date(2026, 10, 1), period_end=period_end)
        assert rpm is True
        assert pcm_ccm is False


class TestClassifyOutcome:
    """Ports `verdict_billing_episode`'s `episode_rollup` outcome/reason CASE."""

    def test_achievement_is_positive_even_before_the_period_closes(self) -> None:
        """`boolor_agg(achieved)` wins the CASE outright — achievement is sticky within the
        period, so an open period with an achieved code is positive, not indeterminate."""
        verdict = rules.classify_outcome(achieved=True, period_end=date(2026, 12, 31), as_of=date(2026, 9, 1))
        assert verdict.outcome == "positive"
        assert verdict.reason is None

    def test_closed_period_without_achievement_is_negative(self) -> None:
        verdict = rules.classify_outcome(achieved=False, period_end=date(2026, 8, 31), as_of=date(2026, 9, 1))
        assert verdict.outcome == "negative"
        assert verdict.reason is None

    def test_period_end_on_as_of_is_closed(self) -> None:
        """`period_end <= as_of` — the boundary day counts as closed."""
        verdict = rules.classify_outcome(achieved=False, period_end=date(2026, 9, 1), as_of=date(2026, 9, 1))
        assert verdict.outcome == "negative"

    def test_open_period_without_achievement_is_indeterminate_period_open(self) -> None:
        verdict = rules.classify_outcome(achieved=False, period_end=date(2026, 12, 31), as_of=date(2026, 9, 1))
        assert verdict.outcome == "indeterminate"
        assert verdict.reason == "period_open"

    def test_stale_facts_give_the_awaiting_source_reason(self) -> None:
        """The dbt model reads source-table recency to say `awaiting_source`; the engine has no
        warehouse read, so staleness arrives as its own consume-loop watermark judgement."""
        verdict = rules.classify_outcome(
            achieved=False,
            period_end=date(2026, 12, 31),
            as_of=date(2026, 9, 1),
            facts_stale=True,
        )
        assert verdict.outcome == "indeterminate"
        assert verdict.reason == "awaiting_source"

    def test_staleness_does_not_reason_a_settled_outcome(self) -> None:
        """Reason is mandatory on indeterminate and absent otherwise (catalog invariant I3)."""
        verdict = rules.classify_outcome(
            achieved=True,
            period_end=date(2026, 12, 31),
            as_of=date(2026, 9, 1),
            facts_stale=True,
        )
        assert verdict.outcome == "positive"
        assert verdict.reason is None


class TestEvaluateEpisode:
    """The episode rollup composed: gate each period's achievement, then classify."""

    def test_any_gated_achievement_qualifies_the_episode(self) -> None:
        verdict = rules.evaluate_episode(
            periods=(
                rules.PeriodFacts(period_end=date(2026, 7, 31), achieved=False, consent_start=date(2026, 1, 1)),
                rules.PeriodFacts(period_end=date(2026, 8, 31), achieved=True, consent_start=date(2026, 1, 1)),
            ),
            as_of=date(2026, 9, 1),
        )
        assert verdict.outcome == "positive"

    def test_achievement_the_consent_gate_clears_does_not_qualify(self) -> None:
        """The gate runs before the rollup: an achievement whose consent postdates the period is
        not achievement at all, so a closed episode of them is negative."""
        verdict = rules.evaluate_episode(
            periods=(rules.PeriodFacts(period_end=date(2026, 8, 31), achieved=True, consent_start=date(2026, 9, 15)),),
            as_of=date(2026, 9, 1),
        )
        assert verdict.outcome == "negative"

    def test_the_latest_period_end_decides_whether_the_episode_closed(self) -> None:
        """`max(period_end)` — one closed period does not close an episode that runs on."""
        verdict = rules.evaluate_episode(
            periods=(
                rules.PeriodFacts(period_end=date(2026, 8, 31), achieved=False, consent_start=date(2026, 1, 1)),
                rules.PeriodFacts(period_end=date(2026, 12, 31), achieved=False, consent_start=date(2026, 1, 1)),
            ),
            as_of=date(2026, 9, 1),
        )
        assert verdict.outcome == "indeterminate"
        assert verdict.reason == "period_open"

    def test_an_episode_with_no_periods_is_indeterminate(self) -> None:
        """No facts is not a negative verdict — there is nothing to have closed."""
        verdict = rules.evaluate_episode(periods=(), as_of=date(2026, 9, 1))
        assert verdict.outcome == "indeterminate"
        assert verdict.reason == "period_open"


class TestPurity:
    def test_no_monetary_field_is_accepted_or_returned(self) -> None:
        """Amount-free billing boundary: the rule surface has no place to put money.
        A `PeriodFacts` is frozen and has only qualification fields."""
        facts = rules.PeriodFacts(period_end=date(2026, 8, 31), achieved=True, consent_start=date(2026, 1, 1))
        assert set(facts.__dataclass_fields__) == {"period_end", "achieved", "consent_start"}
        with pytest.raises((AttributeError, TypeError)):
            facts.amount = 1  # type: ignore[attr-defined]

    def test_verdict_carries_only_outcome_and_reason(self) -> None:
        verdict = rules.classify_outcome(achieved=True, period_end=date(2026, 8, 31), as_of=date(2026, 9, 1))
        assert set(verdict.__dataclass_fields__) == {"outcome", "reason"}
