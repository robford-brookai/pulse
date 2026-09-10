"""The `projection_conformance` classifier (task 2.1): what counts as drift, and what does not.

Pure functions over task 1.3's reader outputs — no reader, no client, no writer is constructed
here, so this module cannot correct the state it polices (design.md decision 2). The caller (task
2.2's CLI) reads each side and hands the results in; this module decides, per
`(subject_type, subject_key)`, which of nine outcomes the pair earns:

| outcome      | what it means                                                                   |
| ------------ | ------------------------------------------------------------------------------- |
| `agreement`  | the consumer cites the snapshot head and its compared fields equal the ledger's |
| `state`      | it cites the head and a compared field differs — the field is named, never its value |
| `lag`        | it cites a sequence behind the head, and the head is older than the consumer's budget |
| `missing`    | the ledger has the subject, the consumer has no row for it, past the budget     |
| `orphan`     | the consumer has a row for a subject the ledger holds no state for              |
| `uncitable`  | the row carries no `ledger_seq` at all — citation is the pass predicate         |
| `in_flight`  | the difference is explained by the snapshot: a post-snapshot citation, or a head committed inside the budget |
| `pre_floor`  | the subject's history lies entirely before `MIN_COMPLETE_FROM`; excluded, never a divergence |
| `malformed`  | a row (or a ledger head) the sweep could not read — counted, never dropped      |

Three rules carry the weight, and each is the reason a whole class of false divergence does not
get reported:

1. **One snapshot per run** (design.md decision 4). Every comparison is against the head pinned
   at the start of the run. A consumer citing *beyond* that head is not ahead of the ledger — it
   applied an event committed while the sweep was running, so it is `in_flight`, not a divergence.
2. **The consumer's freshness budget explains recent movement.** A citation behind the head is
   only `lag` once the head is older than the budget (60 s for the board, 15 min for the landing);
   inside it, the projection is still within its SLO and the pair is `in_flight`. Same rule for a
   subject a consumer has no row for yet: `in_flight` inside the budget, `missing` past it. A
   snapshot with no `head_recorded_at` gets no grace — there is no evidence the head is recent, so
   the strict outcome stands.
3. **The floor is checked before anything else** (design.md decision 5). A subject whose history
   is entirely before `MIN_COMPLETE_FROM` — the head, being its newest event, is the whole test —
   is `pre_floor` whatever its rows look like: the warehouse's history is incomplete there by
   contract, not by loss, so nothing below the floor can be called drift.

Field comparison runs over the *ledger's* field names: the ledger's state is what a projection is
a view of, so a name the ledger models and the consumer lacks (or disagrees on) is a divergence,
and a column the consumer keeps beyond that has nothing to diverge from. Results carry subject
keys and field names only — never a field value from either side, which is what makes a receipt
built over them safe to log whole (spec: "naming the differing field, and carries neither value").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from schedules.sweep_readers import FamilyRead, SubjectRead, SweptRow
from schedules.sweep_registry import Consumer

__all__ = [
    "MIN_COMPLETE_FROM",
    "Comparison",
    "ConsumerConformance",
    "FamilyConformance",
    "Outcome",
    "SubjectSnapshot",
    "UncitableConsumer",
    "compare_family",
    "conform_family",
    "report_uncitable_consumer",
    "report_unconfigured_consumer",
    "snapshot_from_read",
]

#: The warehouse contract's completeness watermark, pinned here and asserted equal to the
#: `min_complete_from` date in `docs/contracts/publishes.md` by a test (design.md decision 5), so
#: the floor this classifier applies cannot drift from the published contract silently. Rows
#: before it are absent from the landing by design; a subject whose history is entirely before it
#: is `pre_floor`, never a divergence.
MIN_COMPLETE_FROM = date(2026, 8, 26)

#: The nine outcomes a compared pair can earn (design.md "Data model and API surface"). Closed on
#: purpose: a receipt's count keys are exactly this set, so a new kind is a spec change, not a
#: string that appears in one family's receipt and nowhere else.
Outcome = Literal[
    "agreement",
    "state",
    "lag",
    "missing",
    "orphan",
    "uncitable",
    "in_flight",
    "pre_floor",
    "malformed",
]


@dataclass(frozen=True)
class SubjectSnapshot:
    """One subject as the ledger stood when the run pinned its head (design.md decision 4).

    `fields` is the folded ledger state (`None` for a subject the ledger holds no state for — a
    consumer row for it is an `orphan`). `head_seq` is the highest sequence the subject has
    committed. `head_recorded_at` is when that head was committed, and is what the freshness
    budget and the floor are measured against; `None` means the caller could not establish it, and
    the classifier then grants no freshness grace and applies no floor exclusion.
    """

    subject_key: str
    head_seq: int | None
    fields: Mapping[str, str] | None
    head_recorded_at: datetime | None = None


@dataclass(frozen=True)
class Comparison:
    """One pair's outcome: the subject key, the consumer that was read, the outcome, and — for
    `state` — the names of the fields that differ, never their values.

    For a `malformed` outcome `subject_key` carries the reader's own position label (a subject key
    where the reader got that far, `[offset n]` where it did not), which is all a malformed row is
    ever allowed to say about itself.
    """

    subject_key: str
    consumer: str
    outcome: Outcome
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class UncitableConsumer:
    """A consumer that cites nothing on any row, reported as a class rather than compared
    (design.md decision 6): its row count for the family and the change that owns its retirement.
    """

    consumer: str
    family: str
    row_count: int
    owning_change: str | None


@dataclass(frozen=True)
class ConsumerConformance:
    """One consumer's whole result for one family: per-subject comparisons, or — for an uncitable
    consumer — the class report and no comparisons at all, or — for a consumer whose source this
    environment does not configure — neither.

    `unconfigured` is the third of those (design.md decision 11): the consumer is registered for
    this family but its source is absent here, so it was skipped and is named in the receipt. It is
    never a divergence and never `no_consumers`; the run's other consumers still compare.
    """

    consumer: str
    family: str
    comparisons: tuple[Comparison, ...] = ()
    uncitable_consumer: UncitableConsumer | None = None
    unconfigured: bool = False

    def counts(self) -> dict[Outcome, int]:
        """Comparisons tallied by outcome. Kinds with no comparisons are absent, not zero —
        the receipt (task 2.2) decides which zeros it prints."""
        return _counts(self.comparisons)

    def subject_keys(self) -> dict[Outcome, tuple[str, ...]]:
        """Subject keys by outcome, in comparison order. Divergences are named individually
        (spec: "Every divergence SHALL appear in the receipt individually by subject key")."""
        return _subject_keys(self.comparisons)


@dataclass(frozen=True)
class FamilyConformance:
    """One family's run across every consumer: the floor applied, the snapshot head, and each
    consumer's result. A family with no registered consumers passes with `no_consumers`
    (design.md decision 6) — it is not a divergence."""

    family: str
    floor: date
    snapshot_head: int | None
    consumers: tuple[ConsumerConformance, ...] = field(default=())

    @property
    def no_consumers(self) -> bool:
        return not self.consumers

    def counts(self) -> dict[Outcome, int]:
        return _counts([c for consumer in self.consumers for c in consumer.comparisons])

    def subject_keys(self) -> dict[Outcome, tuple[str, ...]]:
        return _subject_keys([c for consumer in self.consumers for c in consumer.comparisons])


def _counts(comparisons: Sequence[Comparison]) -> dict[Outcome, int]:
    tally: Counter[Outcome] = Counter(comparison.outcome for comparison in comparisons)
    return dict(tally)


def _subject_keys(comparisons: Sequence[Comparison]) -> dict[Outcome, tuple[str, ...]]:
    keys: dict[Outcome, tuple[str, ...]] = {}
    for comparison in comparisons:
        keys[comparison.outcome] = (*keys.get(comparison.outcome, ()), comparison.subject_key)
    return keys


def snapshot_from_read(
    subject_key: str,
    read: SubjectRead,
    *,
    head_recorded_at: datetime | None = None,
) -> SubjectSnapshot:
    """One `LedgerStateReader.read_subject` result as a snapshot entry.

    `head_recorded_at` is the caller's, not the reader's: `SubjectRead` carries the folded state
    and the head sequence but not the head's commit time, which the caller takes from the same
    history read. Omitting it means "unknown", and the classifier then grants no freshness grace.
    """
    row = read.row
    return SubjectSnapshot(
        subject_key=subject_key,
        head_seq=None if row is None else row.cited_seq,
        fields=None if row is None else row.fields,
        head_recorded_at=head_recorded_at,
    )


def report_uncitable_consumer(*, family: str, consumer: Consumer, row_count: int) -> ConsumerConformance:
    """An uncitable consumer's whole result: its row count and owning change, no comparisons.

    Refuses a citable consumer — that one belongs in `compare_family`, and reporting it as a class
    would hide every divergence it does have.
    """
    if not consumer.uncitable:
        msg = (
            f"consumer {consumer.name!r} cites {consumer.cite_field!r} and is compared per row; "
            "report_uncitable_consumer is only for a consumer with cite_field=None"
        )
        raise ValueError(msg)
    return ConsumerConformance(
        consumer=consumer.name,
        family=family,
        uncitable_consumer=UncitableConsumer(
            consumer=consumer.name,
            family=family,
            row_count=row_count,
            owning_change=consumer.owning_change,
        ),
    )


def report_unconfigured_consumer(*, family: str, consumer: Consumer) -> ConsumerConformance:
    """A registered consumer whose source is not configured for this environment (design.md
    decision 11): named, skipped, and carrying no comparisons at all.

    No comparison is the point — an unconfigured consumer read nothing, so inventing an outcome for
    it would put a count in the receipt that no row backs. `dev01-brook` hosts no OCEAN graph
    database, which is what this reports for `graph-projection-patients` there.
    """
    return ConsumerConformance(consumer=consumer.name, family=family, unconfigured=True)


def compare_family(
    *,
    family: str,
    consumer: Consumer,
    snapshot: Mapping[str, SubjectSnapshot],
    read: FamilyRead,
    as_of: datetime,
    floor: date = MIN_COMPLETE_FROM,
) -> ConsumerConformance:
    """One consumer's rows for one family against the pinned snapshot.

    Every row the reader parsed, every subject the snapshot holds, and every row it could not
    parse is accounted for exactly once: nothing read goes uncounted (spec: "Malformed rows are
    counted and attached"). Refuses an uncitable consumer, which is reported as a class instead
    (spec: "SHALL NOT be compared row by row").
    """
    if consumer.uncitable:
        msg = (
            f"consumer {consumer.name!r} cites no ledger sequence and is reported as a class, "
            "never compared row by row; use report_uncitable_consumer"
        )
        raise ValueError(msg)

    comparisons: list[Comparison] = []
    for row in read.rows:
        comparisons.append(
            _classify_pair(
                snapshot=snapshot.get(row.subject_key),
                row=row,
                consumer=consumer,
                as_of=as_of,
                floor=floor,
            )
        )
    seen = {row.subject_key for row in read.rows}
    for subject_key in sorted(snapshot):
        if subject_key in seen:
            continue
        absent = _classify_absent_row(snapshot=snapshot[subject_key], consumer=consumer, as_of=as_of, floor=floor)
        if absent is not None:
            comparisons.append(absent)
    comparisons.extend(
        Comparison(subject_key=malformed.position, consumer=consumer.name, outcome="malformed")
        for malformed in read.malformed
    )
    return ConsumerConformance(consumer=consumer.name, family=family, comparisons=tuple(comparisons))


def conform_family(
    *,
    family: str,
    snapshot: Mapping[str, SubjectSnapshot],
    consumers: Iterable[ConsumerConformance],
    floor: date = MIN_COMPLETE_FROM,
) -> FamilyConformance:
    """Every consumer's result for one family, plus the floor and snapshot head the run applied.

    `snapshot_head` is the highest sequence any subject in the snapshot had committed — the run's
    one pinned head, which the receipt states so a reader can tell which ledger a receipt is a
    statement about.
    """
    heads = [entry.head_seq for entry in snapshot.values() if entry.head_seq is not None]
    return FamilyConformance(
        family=family,
        floor=floor,
        snapshot_head=max(heads) if heads else None,
        consumers=tuple(consumers),
    )


def _classify_pair(
    *,
    snapshot: SubjectSnapshot | None,
    row: SweptRow,
    consumer: Consumer,
    as_of: datetime,
    floor: date,
) -> Comparison:
    """One consumer row against its snapshot entry. Order is the whole rule: the floor excludes
    before anything is called drift, then citation (the pass predicate), then the snapshot and the
    budget, and only a caught-up citation reaches a field comparison."""
    outcome: Outcome
    if snapshot is None or snapshot.fields is None:
        # The ledger holds no state for this subject key — the consumer's row is a parallel
        # record, not a view (spec: "a subject present in the landing but unknown to the ledger").
        outcome = "orphan"
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome=outcome)
    if _below_floor(snapshot, floor):
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome="pre_floor")
    if row.cited_seq is None:
        # Citation is the pass predicate: matching by value is not conformance.
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome="uncitable")
    if snapshot.head_seq is None:
        # Ledger state with no readable head: not comparable, and not silently an agreement.
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome="malformed")
    if row.cited_seq > snapshot.head_seq:
        # An event committed after the snapshot was pinned; compared against the snapshot only.
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome="in_flight")
    if row.cited_seq < snapshot.head_seq:
        outcome = "in_flight" if _within_budget(snapshot, consumer, as_of) else "lag"
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome=outcome)
    differing = _differing_fields(snapshot.fields, row.fields)
    if differing:
        return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome="state", fields=differing)
    return Comparison(subject_key=row.subject_key, consumer=consumer.name, outcome="agreement")


def _classify_absent_row(
    *,
    snapshot: SubjectSnapshot,
    consumer: Consumer,
    as_of: datetime,
    floor: date,
) -> Comparison | None:
    """A snapshot subject the consumer returned no row for.

    `None` — no comparison at all — for a subject the ledger holds no state for either: there is
    nothing on either side to compare, so counting it would inflate every kind it landed in.
    """
    if snapshot.fields is None:
        return None
    if _below_floor(snapshot, floor):
        return Comparison(subject_key=snapshot.subject_key, consumer=consumer.name, outcome="pre_floor")
    outcome: Outcome = "in_flight" if _within_budget(snapshot, consumer, as_of) else "missing"
    return Comparison(subject_key=snapshot.subject_key, consumer=consumer.name, outcome=outcome)


def _below_floor(snapshot: SubjectSnapshot, floor: date) -> bool:
    """Whether the subject's history lies entirely before the floor. The head is its newest
    event, so the head's date is the whole test; an unknown head time excludes nothing."""
    recorded_at = snapshot.head_recorded_at
    return recorded_at is not None and recorded_at.date() < floor


def _within_budget(snapshot: SubjectSnapshot, consumer: Consumer, as_of: datetime) -> bool:
    """Whether the head is recent enough that the consumer is not yet due to reflect it. An
    unknown head time is not evidence of recency and gets no grace."""
    recorded_at = snapshot.head_recorded_at
    if recorded_at is None:
        return False
    return (as_of - recorded_at).total_seconds() <= consumer.freshness_budget_s


def _differing_fields(ledger: Mapping[str, str], consumer_row: Mapping[str, str]) -> tuple[str, ...]:
    """The ledger field names the consumer row does not match — names only, never values. Runs
    over the ledger's names: a column the consumer keeps beyond the ledger's state has nothing
    to diverge from."""
    return tuple(sorted(name for name, value in ledger.items() if consumer_row.get(name) != value))
