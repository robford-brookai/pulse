"""Declaration — verdict then paired transition through the kit's declare pipeline (task 2.2,
design.md decision 6).

`declare_pair` is the connector's only writer surface: given one `Evaluation`, it submits the
verdict through `pulse_core.connector.declare.submit_with_retry` under the connector's own writer
credential — `client` already carries that credential (`service.py` constructs it from
`config.credential_name`), so this module never reads, holds, or logs a token value — and on a
committed or replayed verdict follows it with the registered pairing contract's transition:
`_TRANSITION_BY_OUTCOME` mirrors `docs/runbooks/billing-state.md`'s pairing table for this
connector's own registered verdict types. `indeterminate` never appears in that table, so it
always declares evidence with no transition (spec: "The connector declares attributed, versioned
verdict pairs"). `idempotency_key` derives the D16-shaped identifier `(subject_key, verdict_type,
rule_version, facts_hash)` names the submission by (`ref`, in `submit_with_retry`'s sense) — the
wire-level D16 key itself is `pulse_core.client.PulseCoreClient.submit_command`'s own concern,
derived from the command's own content and `effective_at`; this identifier is this connector's
readable name for that same fact, safe to log because none of its four parts is a monetary value
or a credential.

`evaluation.as_of` doubles as `effective_at` on every submission in a pair, so the verdict and its
transition derive from the same logical time and replay as a unit — a rerun of the identical
`Evaluation` (same facts, same `as_of`) resubmits byte-identical commands and the ledger answers
both halves as replays (spec: "Re-evaluating unchanged facts declares nothing new").
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pulse_core.client import ResponseClassification
from pulse_core.connector import submit_with_retry
from pulse_core.generated import DeclareTransitionCommand, DeclareVerdictCommand, VerdictOutcome

if TYPE_CHECKING:
    from pulse_core.client import CommandResponse, PulseCoreClient

    from billing_connector.evaluate import Evaluation

logger = logging.getLogger("billing_connector.declare")

#: The connector's registered pairing contract (design.md decision 6): verdict_type -> {outcome
#: -> to_state}, mirrored from `docs/runbooks/billing-state.md`'s pairing table for the verdict
#: types `billing.rules.registry` ships today. A verdict type or outcome absent here declares the
#: verdict only — exactly how `indeterminate` (never a key of the inner mapping) always behaves.
#: Adding a registered type's transition here is a reviewed edit, same as the registry itself
#: (design.md decision 3) — never inferred from the outcome string alone.
_TRANSITION_BY_OUTCOME: dict[str, dict[str, str]] = {
    "billing_eligibility": {"positive": "qualified", "negative": "not_qualified"},
}


@dataclass(frozen=True, slots=True)
class DeclareResult:
    """What declaring one evaluation did: the verdict's own classification, the transition's
    disposition, and the declared event id `evaluate.py`'s caller records on the `evaluations` row.

    `transition_rejected` is `True` only when the verdict itself committed or replayed but its
    paired transition was rejected by the ledger (spec: "A rejected transition keeps its
    evidence" — the verdict's commit and the rejection are both true at once, so this is a flag
    alongside `classification`, never a fourth `classification` value).
    """

    classification: ResponseClassification
    event_id: str | None
    transition_rejected: bool


def idempotency_key(evaluation: Evaluation) -> str:
    """The D16-shaped identifier `(subject_key, verdict_type, rule_version, facts_hash)` derives
    (design.md decision 6) — replay-safe: the same facts for the same subject and verdict type
    under the same rule version always derive the same identifier, so `declare_pair`
    re-submitting an unchanged evaluation names the same submission rather than a new one (spec:
    "Re-evaluating unchanged facts declares nothing new"). None of the four parts is monetary or
    a credential, so this is always safe to log.
    """
    return (
        f"{evaluation.subject.subject_key}:{evaluation.verdict_type}:{evaluation.rule_version}:{evaluation.facts_hash}"
    )


def declare_pair(client: PulseCoreClient, evaluation: Evaluation) -> DeclareResult:
    """Declare one evaluation's verdict, then its paired transition, under one credential.

    Spec: "The connector declares attributed, versioned verdict pairs" — the verdict carries
    `evaluation.rule_version` and is named for retry/logging by `idempotency_key(evaluation)`; a
    committed or replayed verdict is followed by the registered `_TRANSITION_BY_OUTCOME`
    transition, an `indeterminate` verdict declares evidence with no transition. Spec: "No
    monetary value crosses the seam" — every field of `evaluation` this reads is a qualification
    fact or a lineage pointer (`evaluate.py` module docstring), never a monetary value, so no
    amount-bearing value can reach the command payload built here.

    A rejected verdict returns immediately with no transition attempt: the verdict itself never
    took effect, so there is nothing yet to transition. `TransientExhaustedError`
    (`pulse_core.connector.declare`) propagates uncaught — the attempt budget spent, this
    evaluation's declaration failed outright.
    """
    ref = idempotency_key(evaluation)
    verdict = DeclareVerdictCommand(
        subject_key=evaluation.subject.subject_key,
        subject_type=evaluation.subject.subject_type,
        outcome=VerdictOutcome(evaluation.outcome),
        reason=evaluation.reason,
        rule_version=evaluation.rule_version,
        as_of=evaluation.as_of,
        lineage={"verdict_type": evaluation.verdict_type, "facts_hash": evaluation.facts_hash},
    )
    response = _submit(client, verdict, evaluation, ref)
    if response.classification is ResponseClassification.REJECTED:
        _log_rejection(ref, "verdict", response, retried="not retried")
        return DeclareResult(classification=response.classification, event_id=None, transition_rejected=False)

    transition_rejected = False
    to_state = _TRANSITION_BY_OUTCOME.get(evaluation.verdict_type, {}).get(verdict.outcome.value)
    if to_state is not None:
        transition_rejected = _declare_transition(client, evaluation, to_state, ref)

    return DeclareResult(
        classification=response.classification,
        event_id=response.event_id,
        transition_rejected=transition_rejected,
    )


def _declare_transition(client: PulseCoreClient, evaluation: Evaluation, to_state: str, ref: str) -> bool:
    """Follow a committed or replayed verdict with its registered transition.

    Returns whether the ledger rejected it (spec: "A rejected transition keeps its evidence" —
    the verdict's own commit stands either way). The reason cites only the verdict's own keys —
    never an outcome value or anything from the raw facts.
    """
    transition = DeclareTransitionCommand(
        subject_key=evaluation.subject.subject_key,
        subject_type=evaluation.subject.subject_type,
        to_state=to_state,
        reason=(
            f"paired declare_verdict verdict_type={evaluation.verdict_type} rule_version={evaluation.rule_version}"
        ),
    )
    response = _submit(client, transition, evaluation, ref)
    if response.classification is ResponseClassification.REJECTED:
        _log_rejection(ref, "paired transition", response, retried="not retried, the verdict stands")
        return True
    return False


def _submit(
    client: PulseCoreClient,
    command: DeclareVerdictCommand | DeclareTransitionCommand,
    evaluation: Evaluation,
    ref: str,
) -> CommandResponse:
    """Submit one command through the kit's retry loop, `effective_at=evaluation.as_of` for both
    halves of a pair so they derive from the same logical time and replay together."""
    return submit_with_retry(
        lambda: client.submit_command(command, effective_at=evaluation.as_of),
        ref=ref,
        sleep=time.sleep,
        jitter=random.random,
    )


def _log_rejection(ref: str, what: str, response: CommandResponse, *, retried: str) -> None:
    rejection = response.rejection
    logger.warning(
        "evaluation %s %s rejected by the ledger: %s (reason=%s catalog_version=%s); %s",
        ref,
        what,
        rejection.message if rejection else "no detail",
        rejection.reason if rejection else None,
        rejection.catalog_version if rejection else None,
        retried,
    )
