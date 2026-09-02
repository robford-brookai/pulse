"""Declaration — verdict then paired transition through the kit's declare pipeline (task 1.3
stub; behavior fills in at task 2.2, design.md decision 6).

`declare_pair` is the connector's only writer surface: given one `Evaluation`, it submits the
verdict through `pulse_core.connector.declare.submit_with_retry` under the connector's own writer
credential, and on a committed or replayed verdict follows it with the registered pairing
contract's transition — `indeterminate` declares evidence with no transition (spec: "The connector
declares attributed, versioned verdict pairs"). `idempotency_key` derives the D16 key so the pair
replays as a unit rather than twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pulse_core.client import ResponseClassification

if TYPE_CHECKING:
    from pulse_core.client import PulseCoreClient

    from billing_connector.evaluate import Evaluation


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
    """The D16 key `(subject_key, verdict_type, rule_version, facts_hash)` derives (design.md
    decision 6) — replay-safe: the same facts for the same subject and verdict type under the
    same rule version always derive the same key, so `declare_pair` re-submitting an unchanged
    evaluation classifies as replayed rather than declaring twice (spec: "Re-evaluating unchanged
    facts declares nothing new").
    """
    raise NotImplementedError


def declare_pair(client: PulseCoreClient, evaluation: Evaluation) -> DeclareResult:
    """Declare one evaluation's verdict, then its paired transition, under one credential.

    Spec: "The connector declares attributed, versioned verdict pairs" — the verdict carries
    `evaluation.rule_version` and the key `idempotency_key(evaluation)` derives; a committed or
    replayed verdict is followed by the registered `declare_transition`, an `indeterminate`
    verdict declares evidence with no transition. Spec: "No monetary value crosses the seam" — no
    amount-bearing value may reach the command payload this builds. Raises `NotImplementedError`
    until task 2.2.
    """
    raise NotImplementedError
