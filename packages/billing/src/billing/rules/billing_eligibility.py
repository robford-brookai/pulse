"""`billing_eligibility` verdict rules, ported from dbt `verdict_billing_episode`.

Source: `data-platform` `management/models/billing/verdict/verdict_billing_episode.sql`
(the `episode_rollup` CTE and the `new_verdicts` reason CASE) plus the consent gate
`billing_result_stage_3` applies upstream of it. Mapping of every dbt test to its unit test
counterpart: `packages/billing/docs/rule-port-map.md` (connector-pattern task 1.2).

The dbt model's verdict type is `billing_episode_qualified`; pulse's registered vocabulary calls
the same rollup `billing_eligibility` → subject `billing_episode` (`verdict_relay.config`), and
that is the name the engine declares under. The model's other type, `billing_cpt_achieved.99454`,
has no registered counterpart — it is one input to this rollup, never a verdict pulse declares.

Two inputs the dbt model computes from the warehouse do not port and arrive as parameters here:

- per-(period, code) `achieved`, from `billing_result_detailed`'s device/monitoring telemetry
  rollup, which is not a ledger fact (`stays-mart-side` in the map);
- source recency, which the model reads off the raw Mongo billing collections to say
  `awaiting_source`. The engine has no warehouse read, so staleness arrives as `facts_stale` —
  its own consume-loop watermark judgement (design.md decision 3), not a source-table query.

Everything else is pure: same inputs, same verdict, no I/O, no clock, no money.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

#: This implementation's version, distinct from any mart `rule_version`, so a verdict event is
#: attributable to exactly one implementation during the parallel window (design.md decision 4).
RULE_VERSION = "pulse-billing-eligibility-v1"

#: Registered vocabulary: verdict type and the ledger subject it declares against.
VERDICT_TYPE = "billing_eligibility"
SUBJECT_TYPE = "billing_episode"

#: The dbt model's reason vocabulary for an indeterminate verdict. Reason is mandatory on
#: `indeterminate` and absent otherwise (catalog invariant I3).
REASON_PERIOD_OPEN = "period_open"
REASON_AWAITING_SOURCE = "awaiting_source"


@dataclass(frozen=True, slots=True)
class PeriodFacts:
    """One billing period's qualification facts for a subject — no monetary fields, ever.

    `achieved` is the mart-side per-period achievement flag (see the module docstring);
    `consent_start` is ledger-native (`consent.granted`), `None` when no consent is on record.
    """

    period_end: date
    achieved: bool
    consent_start: date | None


@dataclass(frozen=True, slots=True)
class Verdict:
    """An outcome and, only when indeterminate, its mandatory reason."""

    outcome: str
    reason: str | None


def gate_by_consent(*, achieved: bool, consent_start: date | None, period_end: date) -> bool:
    """Apply `billing_result_stage_3`'s consent gate to a period's achievement.

    dbt: `IFF(achieved = TRUE AND consent_start < period_end, TRUE, FALSE)`. A NULL
    `consent_start` makes the predicate NULL and `IFF` returns FALSE, so no consent on record is
    not a pass. The comparison is strict: `assert_consent_gates_achievement` treats
    `consent_start >= period_end` on an achieved row as a violation.

    The gate only ever removes achievement; it never confers it. It is applied per program, so
    two programs' gates read their own consents independently
    (`assert_protocol_change_independent`).
    """
    return achieved and consent_start is not None and consent_start < period_end


def classify_outcome(*, achieved: bool, period_end: date, as_of: date, facts_stale: bool = False) -> Verdict:
    """Classify one subject's rolled-up achievement into a verdict.

    dbt `verdict_billing_episode`, `episode_rollup` CTE::

        case when boolor_agg(achieved)                  then 'positive'
             when max(period_end) <= as_of::date        then 'negative'
             else                                            'indeterminate' end

    with the reason CASE from `new_verdicts`: `awaiting_source` when an indeterminate verdict's
    inputs are stale, `period_open` otherwise. Achievement is sticky within the period — it wins
    the CASE outright, before the period-close test — and a settled outcome carries no reason.

    `achieved` is the rollup (any period achieved, post-gate) and `period_end` the latest period
    end; `evaluate_episode` composes both from a subject's periods.
    """
    if achieved:
        return Verdict(outcome="positive", reason=None)
    if period_end <= as_of:
        return Verdict(outcome="negative", reason=None)
    return Verdict(
        outcome="indeterminate",
        reason=REASON_AWAITING_SOURCE if facts_stale else REASON_PERIOD_OPEN,
    )


def evaluate_episode(*, periods: tuple[PeriodFacts, ...], as_of: date, facts_stale: bool = False) -> Verdict:
    """The episode rollup: gate each period's achievement, then classify the aggregate.

    `boolor_agg(achieved)` over gated periods, `max(period_end)` for the close test. A subject
    with no periods yet has nothing that could have closed, so it is indeterminate rather than
    negative — the dbt model produces no row at all in that case, and a missing row is not a
    negative verdict.
    """
    if not periods:
        return Verdict(
            outcome="indeterminate",
            reason=REASON_AWAITING_SOURCE if facts_stale else REASON_PERIOD_OPEN,
        )
    achieved = any(
        gate_by_consent(achieved=p.achieved, consent_start=p.consent_start, period_end=p.period_end) for p in periods
    )
    return classify_outcome(
        achieved=achieved,
        period_end=max(p.period_end for p in periods),
        as_of=as_of,
        facts_stale=facts_stale,
    )


def evaluate_from_facts(facts: Mapping[str, object], *, as_of: date, facts_stale: bool = False) -> Verdict:
    """The registry calling convention: adapt one subject's flat `subject_facts.facts` snapshot
    into `evaluate_episode`'s input, for `billing_connector.evaluate.evaluate_subject` (task 2.1)
    to call generically through `billing.rules.registry.VERDICT_TYPES` without importing this
    module by name (design.md decision 1). Every registered module exposes this same signature —
    `evaluate_subject` never reads a module's own internal shape (`PeriodFacts`, `evaluate_episode`)
    directly.

    `billing.facts.fold_event` flat-merges each event's payload onto the snapshot rather than
    keeping periods as a list, so a subject row today can only ever describe the one period its
    fields currently name — `period_end`, `achieved`, `consent_start` — never several at once.
    That single period is exactly what `evaluate_episode` (built for the dbt model's multi-period
    rollup) still composes correctly with a one-element tuple; the day a fact source can carry
    more than one open period, this composes them the same way. A facts row with no `period_end`
    yet (an episode subject with only non-eligibility facts folded so far) has nothing to gate:
    treated as no periods, same as `evaluate_episode`'s own no-periods case.
    """
    period_end_raw = facts.get("period_end")
    if period_end_raw is None:
        return evaluate_episode(periods=(), as_of=as_of, facts_stale=facts_stale)

    consent_start_raw = facts.get("consent_start")
    period = PeriodFacts(
        period_end=date.fromisoformat(str(period_end_raw)),
        achieved=bool(facts.get("achieved", False)),
        consent_start=date.fromisoformat(str(consent_start_raw)) if consent_start_raw is not None else None,
    )
    return evaluate_episode(periods=(period,), as_of=as_of, facts_stale=facts_stale)
