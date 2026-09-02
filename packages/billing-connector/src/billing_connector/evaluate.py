"""Evaluation — pure over a subject's fact snapshot plus staleness (task 2.1, design.md
decision 6).

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

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    from billing.store import PostgresFactStore

    from billing_connector.config import Config

#: Reserved key `billing.facts` folds the last-applied event's effective time under — never a
#: real fact field (no envelope payload uses a leading double underscore, `billing.facts` module
#: docstring). Stripped before hashing so `facts_hash` reflects the qualification facts a rule
#: module actually reads, not the fold's own bookkeeping.
_RESERVED_FACT_PREFIX = "__"

#: The registered-module attributes `evaluate_subject` requires before it will run one (spec:
#: "the connector SHALL refuse to start if a registered type has no rule module or a rule module
#: is unregistered").
_REQUIRED_MODULE_ATTRS = ("VERDICT_TYPE", "SUBJECT_TYPE", "RULE_VERSION", "evaluate_from_facts")

REASON_AWAITING_SOURCE = "awaiting_source"


class RegistryMismatchError(RuntimeError):
    """A registered verdict type has no usable rule module (spec: "A registry mismatch halts
    startup") — raised naming the mismatch, never a silent skip. The message is built here, not
    at each call site, so every raise site stays a short, structured call."""

    @classmethod
    def missing_attributes(cls, verdict_type: str, module: ModuleType, missing: list[str]) -> RegistryMismatchError:
        return cls(
            f"registered verdict type {verdict_type!r} (module {module.__name__}) is missing "
            f"required attribute(s): {', '.join(missing)}"
        )

    @classmethod
    def verdict_type_disagrees(cls, verdict_type: str, module: ModuleType) -> RegistryMismatchError:
        return cls(
            f"registry key {verdict_type!r} does not match module {module.__name__}'s own "
            f"VERDICT_TYPE {module.VERDICT_TYPE!r}"
        )


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


def validate_registry(registry: dict[str, ModuleType]) -> None:
    """Refuse a registry entry with no usable rule module behind it (spec: "A registry mismatch
    halts startup"): a missing required attribute, or a module whose own `VERDICT_TYPE` disagrees
    with the key it is registered under.

    Public since task 2.3: `service.main` runs this once at startup, before the first consume
    call, so a mismatched registry halts the process rather than failing on the first delivered
    event (spec scenario: "the connector exits nonzero before consuming, naming the mismatch").
    `evaluate_subject` still calls it per evaluation — the check is cheap, and the two call sites
    guard different things: startup refuses to run at all, per-evaluation refuses to evaluate
    against a registry that changed under a running process.
    """
    for verdict_type, module in registry.items():
        missing = [attr for attr in _REQUIRED_MODULE_ATTRS if not hasattr(module, attr)]
        if missing:
            raise RegistryMismatchError.missing_attributes(verdict_type, module, missing)
        if verdict_type != module.VERDICT_TYPE:
            raise RegistryMismatchError.verdict_type_disagrees(verdict_type, module)


def _facts_hash(facts: dict[str, object]) -> str:
    """A deterministic digest of the qualification facts a rule module actually saw — the input
    to `declare.idempotency_key` (design.md decision 6) — so re-evaluating an unchanged snapshot
    reproduces the same hash regardless of key order (spec: "Re-evaluating unchanged facts
    declares nothing new"). Reserved fold bookkeeping (`__folded_as_of__`) is excluded: it is
    plumbing, not a fact a rule module reads, and would otherwise change the hash on every fold
    even when no real fact moved.
    """
    qualification_facts = {key: value for key, value in facts.items() if not key.startswith(_RESERVED_FACT_PREFIX)}
    canonical = json.dumps(qualification_facts, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_subject(
    store: PostgresFactStore,
    registry: dict[str, ModuleType],
    config: Config,
    subject: SubjectRef,
) -> list[Evaluation]:
    """Evaluate every registered verdict type for one subject's current facts.

    Spec: "Evaluation is event-driven, never batch-gated" (this runs once per folded change,
    called by `service.py`'s consume handler, never on a schedule); "The connector evaluates the
    registered verdict types" (iterates `registry`, restricted to the verdict types registered
    against this subject's own `subject_type` — each module's `SUBJECT_TYPE` says which — and
    refusing to run at all if the registry itself is inconsistent, spec: "A registry mismatch
    halts startup"); "Staleness comes from the connector's own watermark" (derives `facts_stale`
    from `SubjectFactsSnapshot.updated_at` against `config.stale_after`, never a source-table
    recency read; "A subject with no folded events SHALL evaluate as indeterminate with the
    `awaiting_source` reason" when `store.load_snapshot` returns nothing at all).

    Every registered module is called through the shared `evaluate_from_facts(facts, *, as_of,
    facts_stale) -> Verdict` convention (`billing.rules.billing_eligibility`, task 2.1) rather
    than by name, so this function never imports a rule module directly (design.md decision 1).

    Staleness overrides the rule module rather than merely informing it: spec scenario "A stale
    watermark yields awaiting_source" reads unconditionally ("the outcome is indeterminate with
    reason awaiting_source"), not "unless the rule module says otherwise" — so a stale watermark
    short-circuits to `indeterminate`/`awaiting_source` the same way a missing row does, and the
    rule module runs only once this function has already decided the facts are trustworthy
    enough to ask.
    """
    validate_registry(registry)

    applicable = {
        verdict_type: module for verdict_type, module in registry.items() if subject.subject_type == module.SUBJECT_TYPE
    }

    as_of = datetime.now(timezone.utc)
    snapshot = store.load_snapshot(subject.subject_type, subject.subject_key)

    facts_stale = snapshot is None or snapshot.updated_at is None or (as_of - snapshot.updated_at) > config.stale_after
    facts_hash = _facts_hash({}) if snapshot is None else _facts_hash(dict(snapshot.facts))

    evaluations: list[Evaluation] = []
    for verdict_type, module in applicable.items():
        if facts_stale or snapshot is None:
            outcome, reason = "indeterminate", REASON_AWAITING_SOURCE
        else:
            verdict = module.evaluate_from_facts(snapshot.facts, as_of=as_of.date(), facts_stale=False)
            outcome, reason = verdict.outcome, verdict.reason
        evaluations.append(
            Evaluation(
                subject=subject,
                verdict_type=verdict_type,
                rule_version=module.RULE_VERSION,
                outcome=outcome,
                reason=reason,
                facts_stale=facts_stale,
                facts_hash=facts_hash,
                as_of=as_of,
            )
        )
    return evaluations
