"""Evaluation — pure over a subject's fact snapshot plus staleness (task 1.3 stub; behavior fills
in at task 2.1, design.md decision 6).

`evaluate_subject` is the connector's own read-then-decide step: for one subject, load its
`billing_engine.subject_facts` row through `store`, derive `facts_stale` from the row's watermark
against `config.stale_after`, run every rule module `registry` lists for that subject's type, and
return one `Evaluation` per registered verdict type — never a warehouse read (spec: "Evaluation is
event-driven, never batch-gated"; "The connector evaluates the registered verdict types";
"Staleness comes from the connector's own watermark"). `service.py` calls this once per folded
change; nothing here talks to a queue, a clock outside `as_of`, or the command API — `declare.py`
owns declaring the result.

Every field on `Evaluation` is a qualification fact or a lineage pointer, never a monetary value
(spec: "No monetary value crosses the seam") — task 2.1's fill is what proves that in practice, but
the shape is fixed here so nothing added later widens it by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    from billing_connector.config import Config


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """The two-part key `billing_engine.subject_facts` and every rule module key off: the
    ledger's own `(subject_type, subject_key)` pair, never a bare id (`billing.store`,
    `billing.facts.SubjectFactsSnapshot`)."""

    subject_type: str
    subject_key: str


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One verdict type's evaluated outcome for one subject, ready for `declare.declare_pair`.

    `facts_hash` is the input to the D16 idempotency key (`declare.idempotency_key`,
    `(subject_key, verdict_type, rule_version, facts_hash)`, design.md decision 6) — a hash of the
    exact fact snapshot the rule module saw, so re-evaluating unchanged facts reproduces the same
    hash and the same key (spec: "Re-evaluating unchanged facts declares nothing new"). `reason` is
    populated only when `outcome` is `indeterminate` (catalog invariant I3, mirrored from
    `billing.rules.billing_eligibility.Verdict`).
    """

    subject: SubjectRef
    verdict_type: str
    rule_version: str
    outcome: str
    reason: str | None
    facts_stale: bool
    facts_hash: str
    as_of: datetime


def evaluate_subject(
    store: object,
    registry: dict[str, ModuleType],
    config: Config,
    subject: SubjectRef,
) -> list[Evaluation]:
    """Evaluate every registered verdict type for one subject's current facts.

    Spec: "Evaluation is event-driven, never batch-gated" (this runs once per folded change,
    called by `service.py`'s consume handler, never on a schedule); "The connector evaluates the
    registered verdict types" (iterates `registry`, refusing to start elsewhere — task 2.1 — if a
    registered type has no module); "Staleness comes from the connector's own watermark" (derives
    `facts_stale` from the subject's fact watermark against `config.stale_after`, never a
    source-table recency read).

    `store` is typed `object` here rather than `billing.store.PostgresFactStore` because the read
    method this needs (a subject's current snapshot plus its `updated_at` watermark) does not
    exist on that class yet — task 2.1 adds it and narrows this parameter's type along with the
    body (see `HANDOFF.md`). Raises `NotImplementedError` until then.
    """
    raise NotImplementedError
