"""`Receipt` — the one shape every registry sweep's run ends in (task 2.2, design.md decision 7).

`projection_conformance` (task 2.1) and `consent_sweep`'s `export_diff` (tasks 3.1-3.2, unchanged)
report their runs in two different native shapes — a `FamilyConformance` of per-consumer
`Comparison`s, and a `DriftReceipt` tally over `Correction`s. This module is the one place both
fold into the receipt design.md decision 7 pins: `date`, `family`, `kind`, `floor`, `snapshot_head`,
and — per consumer — `agreements`, `divergences` by kind, `uncitable`, `in_flight`, `malformed`,
`pre_floor`, `unconfigured` (design.md decision 11: a registered consumer whose source this
environment does not host — named, skipped, never a divergence), plus `subject_keys` by kind
capped at 200 with the total count beside the cap; tagged
`project:pulse`, `service:schedules`, `family:<name>`. "The same line is the receipt posted on the
tracking issue after an attended run" — one shape, whichever sweep kind produced it, is what makes
that possible.

`build_projection_conformance_receipt` reads a `FamilyConformance` straight off its own
`counts()`/`subject_keys()`, one `ConsumerReceipt` per registered consumer (an uncitable consumer's
own class report becomes a `ConsumerReceipt` whose only non-zero field is `uncitable`, so uncitable
consumers and compared ones print through the same shape without a receipt-level special case;
an unconfigured consumer prints the same way, with `unconfigured` true and every count zero).
`build_export_diff_receipt` has no registered consumer to iterate — the export itself is the
lone side being reconciled against the ledger — so it reports one fixed `ConsumerReceipt` named
`EXPORT_DIFF_CONSUMER`, mapping every declared correction to a `state` divergence (D9: the export's
authority over the ledger *is* the disagreement this receipt names) and every unparseable row to
`malformed`.

Never a payload value, payer identifier, or demographic anywhere in this module — every field
above is a subject key, a field *name*, or a count.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from schedules.consent_sweep import Correction, DriftReceipt, ExportParseError
from schedules.projection_conformance import FamilyConformance
from schedules.sweep_registry import SweepKind

__all__ = [
    "EXPORT_DIFF_CONSUMER",
    "SUBJECT_KEY_CAP",
    "ConsumerReceipt",
    "Receipt",
    "SubjectKeyTally",
    "build_export_diff_receipt",
    "build_projection_conformance_receipt",
    "compute_streak",
    "receipt_payload",
    "rows_compared",
]

#: The most subject keys a receipt names per outcome kind (design.md decision 7). Past the cap, a
#: receipt still states how many keys that kind actually holds — the cap bounds a run's logged
#: payload size, never its truthfulness about how much drift there was.
SUBJECT_KEY_CAP = 200

#: The `export_diff` receipt's one fixed consumer name: there is no registry consumer for it (the
#: sweep reconciles the export against the ledger directly), so this stands in for "the consumer"
#: wherever a `projection_conformance` receipt would otherwise name a registered one.
EXPORT_DIFF_CONSUMER = "export"

#: `Comparison.outcome`s that count as divergence for `ConsumerReceipt.divergences` (design.md
#: decision 7: "divergences by kind (state, lag, missing, orphan)"). `uncitable`, `in_flight`,
#: `malformed`, and `pre_floor` are each their own receipt field instead — an outcome names exactly
#: one of these five places, never two.
_DIVERGENCE_KINDS: tuple[str, ...] = ("state", "lag", "missing", "orphan")


@dataclass(frozen=True)
class SubjectKeyTally:
    """One outcome kind's subject keys, capped, with the total beside the cap (design.md decision
    7: "subject_keys by kind capped at 200 ... with the total count beside the cap"). `total` is
    always the true count, even when `keys` was truncated to fit `SUBJECT_KEY_CAP` — a reader never
    has to guess whether `len(keys) == total` means "that's all of them" or "the cap landed exactly
    there".
    """

    keys: tuple[str, ...]
    total: int


def _tally(keys: Sequence[str]) -> SubjectKeyTally:
    return SubjectKeyTally(keys=tuple(keys[:SUBJECT_KEY_CAP]), total=len(keys))


@dataclass(frozen=True)
class ConsumerReceipt:
    """One consumer's slice of a family's receipt (design.md decision 7's "per consumer" fields).

    `divergences` is keyed by the four divergence kinds that had at least one comparison land in
    them — a kind with zero divergences is absent, not zero, matching
    `ConsumerConformance.counts`'s own "kinds with no comparisons are absent" rule.
    `subject_keys` carries a `SubjectKeyTally` for every outcome this consumer had at least one of,
    divergence kinds included, so a reader can always name which subjects a count is about.
    """

    consumer: str
    agreements: int = 0
    divergences: Mapping[str, int] = field(default_factory=dict[str, int])
    uncitable: int = 0
    in_flight: int = 0
    malformed: int = 0
    pre_floor: int = 0
    subject_keys: Mapping[str, SubjectKeyTally] = field(default_factory=dict[str, SubjectKeyTally])
    unconfigured: bool = False

    @property
    def is_clean(self) -> bool:
        """No divergence of any kind — the streak predicate (spec: "zero divergences"). Agreement,
        uncitable, in_flight, malformed and pre_floor counts do not affect a streak: they are not
        divergences by design.md decision 7's own grouping. Neither does `unconfigured`: a consumer
        whose source this environment does not host read nothing, and nothing read is nothing to
        diverge from (design.md decision 11)."""
        return not any(self.divergences.values())


@dataclass(frozen=True)
class Receipt:
    """One family's whole receipt for one run (design.md decision 7). `no_consumers` mirrors
    `FamilyConformance.no_consumers` — a family with zero registered consumers passes with this
    `True` and `consumers=()` (design.md decision 6); `export_diff` receipts are never
    `no_consumers`, since the export is always compared against the ledger.
    """

    date: date
    family: str
    kind: SweepKind
    floor: date
    snapshot_head: int | None
    consumers: tuple[ConsumerReceipt, ...] = ()
    no_consumers: bool = False
    tags: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        """Every consumer clean (spec: "Ten clean receipts are readable as a streak")."""
        return all(consumer.is_clean for consumer in self.consumers)


def _tags(family: str) -> tuple[str, ...]:
    """Design.md decision 7's fixed tag set, family-scoped so the observability plan's drift trend
    can filter to one family's stream."""
    return ("project:pulse", "service:schedules", f"family:{family}")


def build_projection_conformance_receipt(conformance: FamilyConformance, *, run_date: date) -> Receipt:
    """One `projection_conformance` run's `FamilyConformance` as a `Receipt`.

    Reads straight off `ConsumerConformance.counts()`/`subject_keys()` — this function computes
    nothing about drift itself, only reshapes what task 2.1's classifier already decided. An
    uncitable consumer (`ConsumerConformance.uncitable_consumer` set, `comparisons` empty) reports
    its row count as `uncitable` and no `subject_keys` at all: a row count is not a subject key, and
    reporting it as one would misstate what the consumer actually returned (design.md decision 6:
    "reported as a class ... and never compared per row").
    """
    consumers: list[ConsumerReceipt] = []
    for consumer in conformance.consumers:
        if consumer.unconfigured:
            # No source here, so no row was read: every count stays zero and the flag is the whole
            # statement (design.md decision 11). It is a registered consumer of this family all the
            # same, so the receipt is not `no_consumers`.
            consumers.append(ConsumerReceipt(consumer=consumer.consumer, unconfigured=True))
            continue
        if consumer.uncitable_consumer is not None:
            consumers.append(
                ConsumerReceipt(consumer=consumer.consumer, uncitable=consumer.uncitable_consumer.row_count)
            )
            continue
        counts = consumer.counts()
        subject_keys = consumer.subject_keys()
        consumers.append(
            ConsumerReceipt(
                consumer=consumer.consumer,
                agreements=counts.get("agreement", 0),
                divergences={kind: counts[kind] for kind in _DIVERGENCE_KINDS if kind in counts},
                uncitable=counts.get("uncitable", 0),
                in_flight=counts.get("in_flight", 0),
                malformed=counts.get("malformed", 0),
                pre_floor=counts.get("pre_floor", 0),
                subject_keys={outcome: _tally(keys) for outcome, keys in subject_keys.items()},
            )
        )
    return Receipt(
        date=run_date,
        family=conformance.family,
        kind="projection_conformance",
        floor=conformance.floor,
        snapshot_head=conformance.snapshot_head,
        consumers=tuple(consumers),
        no_consumers=conformance.no_consumers,
        tags=_tags(conformance.family),
    )


def _export_correction_subject_key(correction: Correction) -> str:
    """The (subject, channel) grain a consent correction names — the same composed key
    `consent_sweep._ledger_key` builds internally, restated here rather than imported, since a
    receipt names subject keys and this is the only fact about that internal helper this module
    needs (never the channel or state alone, which said nothing new beyond the key itself)."""
    return f"{correction.subject_key}:{correction.channel}"


def _export_parse_error_position(error: ExportParseError) -> str:
    """An unparseable export row's position — the row number, never its other contents (spec:
    "Malformed rows are counted and attached"; `ExportParseError` itself never carries a raw
    value)."""
    return f"row:{error.row_number}"


def build_export_diff_receipt(
    drift: DriftReceipt,
    *,
    family: str,
    run_date: date,
    floor: date,
    corrections: Sequence[Correction] = (),
) -> Receipt:
    """One `export_diff` (consent sweep) run's `DriftReceipt` as a `Receipt`.

    `corrections` is `diff_consent`'s own output for this run — the same sequence `drift` was
    tallied from — passed separately because `DriftReceipt` keeps only the counts, not which
    subjects they were (task 3.3 never needed subject keys; this receipt does, design.md decision
    7: "subject_keys by kind"). Every correction becomes a `state` divergence: D9 makes the export
    authoritative, so a correction *is* the ledger disagreeing with the export's record, the same
    disagreement a ledger-owned family's `state` divergence names. `snapshot_head` is always `None`
    — an export diff cites no ledger sequence at all, unlike a `projection_conformance` consumer.
    """
    state_keys = tuple(_export_correction_subject_key(correction) for correction in corrections)
    malformed_keys = tuple(_export_parse_error_position(error) for error in drift.parse_errors)
    divergences: dict[str, int] = {}
    if drift.total_corrections:
        divergences["state"] = drift.total_corrections
    subject_keys: dict[str, SubjectKeyTally] = {}
    if state_keys:
        subject_keys["state"] = _tally(state_keys)
    if malformed_keys:
        subject_keys["malformed"] = _tally(malformed_keys)
    consumer = ConsumerReceipt(
        consumer=EXPORT_DIFF_CONSUMER,
        agreements=drift.agreements,
        divergences=divergences,
        malformed=drift.unparseable,
        subject_keys=subject_keys,
    )
    return Receipt(
        date=run_date,
        family=family,
        kind="export_diff",
        floor=floor,
        snapshot_head=None,
        consumers=(consumer,),
        no_consumers=False,
        tags=_tags(family),
    )


def rows_compared(receipt: Receipt) -> int:
    """How many rows this receipt's run actually classified — the process exit contract's own
    predicate (design.md decision 10: exit 2 "when no rows could be compared at all"). Every
    outcome a consumer landed in counts, `malformed` included: a row the sweep could not parse was
    still read and accounted for, which is not the same as nothing being read at all."""
    total = 0
    for consumer in receipt.consumers:
        total += consumer.agreements + sum(consumer.divergences.values())
        total += consumer.uncitable + consumer.in_flight + consumer.malformed + consumer.pre_floor
    return total


def compute_streak(receipts: Sequence[Receipt]) -> int:
    """The number of consecutive, unbroken, clean calendar days at the end of `receipts` (spec:
    "Ten clean receipts are readable as a streak" — "the streak is computable from the receipt
    lines alone"). `receipts` may be given in any order and for any single family; sorted by date
    here so callers never have to pre-sort their own receipt stream. The streak breaks on the first
    receipt (scanning from the most recent day backward) that is not clean, or on a gap in the
    calendar — a missing day is not evidence of a clean one.
    """
    ordered = sorted(receipts, key=lambda receipt: receipt.date, reverse=True)
    streak = 0
    previous_date: date | None = None
    for receipt in ordered:
        if previous_date is not None and (previous_date - receipt.date).days != 1:
            break
        if not receipt.is_clean:
            break
        streak += 1
        previous_date = receipt.date
    return streak


def _subject_key_tally_payload(tally: SubjectKeyTally) -> dict[str, object]:
    return {"keys": list(tally.keys), "total": tally.total}


def _consumer_payload(consumer: ConsumerReceipt) -> dict[str, object]:
    return {
        "consumer": consumer.consumer,
        "agreements": consumer.agreements,
        "divergences": dict(consumer.divergences),
        "uncitable": consumer.uncitable,
        "in_flight": consumer.in_flight,
        "malformed": consumer.malformed,
        "pre_floor": consumer.pre_floor,
        "unconfigured": consumer.unconfigured,
        "subject_keys": {
            outcome: _subject_key_tally_payload(tally) for outcome, tally in consumer.subject_keys.items()
        },
    }


def receipt_payload(receipt: Receipt) -> dict[str, object]:
    """The receipt as one JSON-ready object — the line the CLI prints and the same line a runbook
    posts on the tracking issue after an attended run (design.md decision 7)."""
    return {
        "date": receipt.date.isoformat(),
        "family": receipt.family,
        "kind": receipt.kind,
        "floor": receipt.floor.isoformat(),
        "snapshot_head": receipt.snapshot_head,
        "no_consumers": receipt.no_consumers,
        "consumers": [_consumer_payload(consumer) for consumer in receipt.consumers],
        "tags": list(receipt.tags),
    }
