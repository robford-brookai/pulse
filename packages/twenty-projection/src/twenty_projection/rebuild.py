"""The authoritative rebuild: the board repainted from the ledger's committed events alone.

A projection is a window painted from the journal, and the proof that it is a window and not a
second copy of the truth is that it can be destroyed and repainted from the journal — row for row,
field for field. This module is that operation, as an operator command rather than a test-only
trick (`projection-rebuild` spec; pulse-demo-closeout design decision 4).

    task projection:rebuild TARGET=dev SCOPE=enrollment:pt-0001 OPERATOR=<who>

What it does, per subject in the named scope:

1. Read the subject's committed events from the ledger's replay route, in ledger sequence
   (`PulseCoreClient.subject_history`, task 1.3) — over HTTP, never from the ledger's database.
2. Fold them through the *same* handler the live consumer applies (`apply.projected_fields`, under
   the same `is_watermark_stale` guard), per program, because per program is per board row.
3. Diff the folded state against the row that is there now, field by field.
4. Write only differences, as one full-state PATCH — the same write the live path makes.
5. Count everything and print a receipt: scope, rows read, events read, rows written, differences,
   attributable to the operator who ran it.

**"Destroyed" means the columns the projection owns.** The projection never creates a board record
— it resolves one through the denormalized `canonicalPatientId` / `programCode` columns and
repaints `lifecycleStatus`, its as-of, and the watermark. So a destroyed projection is a row whose
projected columns are gone, not a deleted row: deleting the row would delete the subject's anchor,
which the projection has no authority to create and therefore must not destroy. A subject whose
row is absent is a counted orphan, the same disposition the live path parks
(`handling.handle_event`), never a created record.

**Why the fold cannot disagree with live apply.** It shares the state function and the ordering
guard with `apply_event`, and it reads events in the order the relay published them, which is the
order the live consumer saw them in and the order its watermark is stated over. A backdated event
(a later `seq` carrying an earlier `effective_at`) therefore wins here exactly as it won live: the
write is full state, and the last event in ledger sequence is the whole answer. A fold that instead
ordered by effective time would produce a defensible-looking row that the live path never had — it
would pass a demo and lie.

**Credential posture.** Two credentials, each named by whoever owns the facility: the projection's
own Twenty token (`PULSE_TWENTY_<TARGET>_TOKEN`, the twenty-deploy convention, this package's one
credential) and the kit's replay credential (`pulse_core.replay`, which owns that name for every
connector that repaints itself). No ledger DSN, no database driver, no `pulse_ledger` import.

**Log and receipt posture.** Identifiers, programs, sequences, and *field names* only. A difference
is reported as the name of the column that differed, never as the value on either side — an event
payload is patient data once C1 clears, and a receipt is a thing people paste into tickets.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from pulse_core.client import PulseCoreClient, SubjectHistoryRefusedError
from pulse_core.connector import is_watermark_stale
from pulse_core.replay import (
    REPLAY_BASE_URL_ENV_VAR,
    REPLAY_TOKEN_ENV_VAR,
    ReplayStartupError,
    replay_client_from_env,
)

from twenty_projection.apply import (
    DEFAULT_LIST_PAGE_SIZE,
    FILTER_RESERVED,
    V1_BOARD,
    AmbiguousSubjectError,
    BoardTarget,
    EnrollmentEvent,
    ProjectionApplyError,
    ProjectionRestClient,
    SubjectLookupError,
    parse_envelope,
    projected_fields,
)
from twenty_projection.consumer import env_var_names

logger = logging.getLogger(__name__)

#: The identity a replay read is made under. Reaches nothing on a read path (it seeds the
#: idempotency key of a *submitted* command), but no read is made anonymously.
PROJECTION_WRITER_ID = "twenty-projection"

#: The board columns that carry the subject's identity. Never written, only read: the projection
#: resolves through them and would have nothing to resolve if it could change them.
SUBJECT_COLUMN = "canonicalPatientId"
PROGRAM_COLUMN = "programCode"


class ProjectionRebuildError(Exception):
    """Base for the rebuild's own typed failures. Never carries payload content."""


class ScopeError(ProjectionRebuildError):
    """The scope is not one this rebuild can run — names the scope, never a payload value.

    One subclass per way a scope can be wrong, each owning its own reason, so a raise site passes
    the scope and nothing else. The scope is operator input, echoed back so they can see what was
    read; it carries no event payload by construction.
    """

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(f"scope {scope!r} cannot be rebuilt: {self.reason}")

    @property
    def reason(self) -> str:
        return "expected <subject_type>[:<key>]"


class EmptyScopeError(ScopeError):
    @property
    def reason(self) -> str:
        return "it is empty — expected <subject_type>[:<key>]"


class MalformedScopeError(ScopeError):
    @property
    def reason(self) -> str:
        return "expected <subject_type>[:<key>], with one ':' at most and neither half empty"


class ReservedScopeKeyError(ScopeError):
    @property
    def reason(self) -> str:
        return "its key carries a character the board's filter grammar reserves, which has no predicate"


class UnrenderedSubjectTypeError(ScopeError):
    """The scope names a subject type this board does not project — halt, never a guessed board."""

    def __init__(self, scope: str, *, board: BoardTarget) -> None:
        self.board_object = board.object_name
        self.board_subject_type = board.subject_type
        super().__init__(scope)

    @property
    def reason(self) -> str:
        return f"board {self.board_object!r} renders subject type {self.board_subject_type!r}"


class HistoryScopeError(ProjectionRebuildError):
    """A history read answered with an event for another subject.

    Raised rather than folded: a replay source that mixes subjects would repaint one subject's row
    from another's events, which is the one failure a rebuild must never make quietly.
    """

    def __init__(self, *, requested: str, received: str) -> None:
        self.requested = requested
        self.received = received
        super().__init__(f"history for subject {requested!r} carried an event for {received!r}")


class RebuildStartupError(ProjectionRebuildError):
    """The rebuild's environment is incomplete — names every absent variable, never a value."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"rebuild is not configured — set: {', '.join(missing)}")


class HistorySource(Protocol):
    """The replay surface the rebuild reads: one subject's committed events, in ledger sequence.

    `PulseCoreClient` satisfies it structurally, which is the point — the rebuild depends on the
    shape of the read, not on the client, so a test hands it a fixture history and holds no
    credential at all.
    """

    def subject_history(self, subject_type: str, subject_key: str) -> Sequence[Mapping[str, object]]: ...


@dataclass(frozen=True)
class Scope:
    """What a rebuild was asked to repaint: one subject type, and optionally one subject."""

    subject_type: str
    subject_key: str | None

    @property
    def label(self) -> str:
        """The scope as the operator typed it — the receipt's first line."""
        return self.subject_type if self.subject_key is None else f"{self.subject_type}:{self.subject_key}"


def parse_scope(raw: str) -> Scope:
    """`<subject_type>[:<key>]`, or a `ScopeError` naming what is wrong with it.

    Refused rather than interpreted: an empty half (`enrollment:`, `:pt-0001`), a second colon, or
    a key carrying a character Twenty's filter grammar reserves. That last one has no expressible
    predicate — the grammar has no quoting, so a comma in a key would silently become a second
    filter — and the apply core refuses such a key for the same reason.
    """
    scope = raw.strip()
    if not scope:
        raise EmptyScopeError(raw)
    if scope.count(":") > 1:
        raise MalformedScopeError(raw)
    subject_type, separator, subject_key = scope.partition(":")
    if not subject_type or (separator and not subject_key):
        raise MalformedScopeError(raw)
    if subject_key and FILTER_RESERVED & set(subject_key):
        raise ReservedScopeKeyError(raw)
    return Scope(subject_type=subject_type, subject_key=subject_key or None)


@dataclass(frozen=True)
class FoldedState:
    """One subject-program's state after the fold: the full board state its last event implies."""

    subject_key: str
    program: str
    seq: int
    event_id: str
    fields: Mapping[str, object]


def fold_history(
    envelopes: Iterable[Mapping[str, object]],
    *,
    board: BoardTarget = V1_BOARD,
    subject_key: str | None = None,
) -> dict[str, FoldedState]:
    """Fold one subject's committed events to the board state they imply, keyed by program.

    Per program, because per program is per board row: an `enrollment` subject key is the canonical
    patient id and the program travels in the payload, so one subject's history can address several
    rows and each row carries its own watermark.

    The guard is `is_watermark_stale` — the same one live apply applies to a record's persisted
    watermark, here against the running one — so an event that could not have moved the row live
    cannot move it here either. Events arrive in ledger sequence, which makes the guard a no-op in
    the ordinary case; sharing it is what makes that a property rather than an assumption.

    `subject_key`, when given, is asserted against every envelope: a replay source that answered
    with another subject's events would otherwise repaint the wrong row.
    """
    folded: dict[str, FoldedState] = {}
    for envelope in envelopes:
        event = parse_envelope(envelope, board)
        if subject_key is not None and event.subject_key != subject_key:
            raise HistoryScopeError(requested=subject_key, received=event.subject_key)
        current = folded.get(event.program)
        if current is not None and is_watermark_stale(event.seq, current.seq):
            logger.info(
                "rebuild fold skip: event %s for subject %s program %s seq %s is at or below folded seq %s",
                event.event_id,
                event.subject_key,
                event.program,
                event.seq,
                current.seq,
            )
            continue
        folded[event.program] = _folded(event, board)
    return folded


def _folded(event: EnrollmentEvent, board: BoardTarget) -> FoldedState:
    return FoldedState(
        subject_key=event.subject_key,
        program=event.program,
        seq=event.seq,
        event_id=event.event_id,
        fields=projected_fields(event, board),
    )


@dataclass(frozen=True)
class SubjectOutcome:
    """What the rebuild did for one subject-program, in names and counts only.

    `disposition` is one of `written`, `unchanged`, `orphan` (no board row for the subject), or
    `no_events` (the subject's journal is empty, so there is no state to paint).
    """

    subject_key: str
    program: str | None
    record_ref: str | None
    events_read: int
    differing_fields: tuple[str, ...]
    disposition: str


@dataclass(frozen=True)
class RebuildReceipt:
    """The counted, attributable record of one rebuild — safe to paste anywhere."""

    scope: str
    operator: str
    subjects: int = 0
    rows_read: int = 0
    events_read: int = 0
    rows_written: int = 0
    differences: int = 0
    orphans: int = 0
    outcomes: tuple[SubjectOutcome, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """The receipt as an operator reads it: counts, then one line per subject-program.

        Field *names* are the vocabulary for a difference. No value from either side of the diff
        appears here, which is what makes the receipt safe to attach to an issue.
        """
        lines = [
            "projection rebuild receipt",
            f"  scope:        {self.scope}",
            f"  operator:     {self.operator}",
            f"  subjects:     {self.subjects}",
            f"  rows read:    {self.rows_read}",
            f"  events read:  {self.events_read}",
            f"  rows written: {self.rows_written}",
            f"  differences:  {self.differences}",
            f"  orphans:      {self.orphans}",
        ]
        for outcome in self.outcomes:
            program = outcome.program or "-"
            fields = ",".join(outcome.differing_fields) or "-"
            lines.append(
                f"  - {outcome.subject_key} {program}: {outcome.disposition} "
                f"(events {outcome.events_read}, fields {fields})"
            )
        return "\n".join(lines)


def rebuild(
    scope: Scope,
    *,
    history: HistorySource,
    client: ProjectionRestClient,
    operator: str,
    board: BoardTarget = V1_BOARD,
    page_size: int = DEFAULT_LIST_PAGE_SIZE,
) -> RebuildReceipt:
    """Repaint the named scope from the journal, writing only differences, and receipt it.

    Safe to rerun by construction: the write is a diff against what is there, so a second run with
    no intervening events writes nothing and reports zero differences.

    Rows outside the scope are never listed into the fold and never written — the scope's board
    listing *is* the set of rows this run can touch, and nothing here deletes a row at all.

    Raises `ScopeError` for a scope this board does not render, `AmbiguousSubjectError` when the
    key columns are not unique for a subject-program (a data fault, never a picked winner),
    `SubjectHistoryRefusedError` when the replay read is not a readable history, and
    `ProjectionWriteError` when a write fails.
    """
    if scope.subject_type != board.subject_type:
        raise UnrenderedSubjectTypeError(scope.label, board=board)

    rows = _rows_in_scope(scope, client=client, board=board, page_size=page_size)
    subject_keys = [scope.subject_key] if scope.subject_key is not None else sorted({key for key, _ in rows})

    outcomes: list[SubjectOutcome] = []
    events_read = 0
    rows_written = 0
    differences = 0
    orphans = 0

    for subject_key in subject_keys:
        events = history.subject_history(board.subject_type, subject_key)
        events_read += len(events)
        folded = fold_history(events, board=board, subject_key=subject_key)
        if not folded:
            logger.info("rebuild no-op: subject %s has no committed events for %s", subject_key, board.subject_type)
            outcomes.append(
                SubjectOutcome(
                    subject_key=subject_key,
                    program=None,
                    record_ref=None,
                    events_read=len(events),
                    differing_fields=(),
                    disposition="no_events",
                )
            )
            continue
        for program in sorted(folded):
            outcome = _rebuild_one(folded[program], rows.get((subject_key, program)), client=client, board=board)
            outcomes.append(outcome)
            differences += len(outcome.differing_fields)
            rows_written += outcome.disposition == "written"
            orphans += outcome.disposition == "orphan"

    return RebuildReceipt(
        scope=scope.label,
        operator=operator,
        subjects=len(subject_keys),
        rows_read=len(rows),
        events_read=events_read,
        rows_written=rows_written,
        differences=differences,
        orphans=orphans,
        outcomes=tuple(outcomes),
    )


def _rows_in_scope(
    scope: Scope,
    *,
    client: ProjectionRestClient,
    board: BoardTarget,
    page_size: int,
) -> dict[tuple[str, str], Mapping[str, object]]:
    """The board rows this scope may touch, keyed by the identity columns the projection resolves on.

    One listing for the whole run: the rows are both the enumeration of projected subjects (for a
    keyless scope) and the "before" side of every diff, so reading them once is also what makes
    "rows outside the scope are untouched" a property of the run rather than a promise.
    """
    filters = {SUBJECT_COLUMN: scope.subject_key} if scope.subject_key is not None else None
    rows: dict[tuple[str, str], Mapping[str, object]] = {}
    for record in client.list_records(board.plural, filters=filters, page_size=page_size):
        subject_key = record.get(SUBJECT_COLUMN)
        program = record.get(PROGRAM_COLUMN)
        if not isinstance(subject_key, str) or not subject_key or not isinstance(program, str) or not program:
            # A row with no identity columns is not addressable by any subject, so no event can
            # resolve to it and no rebuild can paint it. Counted nowhere, touched never.
            logger.info("rebuild skip: a %s row carries no subject identity columns", board.object_name)
            continue
        identity = (subject_key, program)
        if identity in rows:
            raise AmbiguousSubjectError(subject_key=subject_key, program=program, count=2)
        rows[identity] = record
    return rows


def _rebuild_one(
    state: FoldedState,
    record: Mapping[str, object] | None,
    *,
    client: ProjectionRestClient,
    board: BoardTarget,
) -> SubjectOutcome:
    """Diff one folded state against one row and write it only if they differ."""
    if record is None:
        logger.warning(
            "rebuild orphan: no %s row for subject %s program %s (event %s)",
            board.object_name,
            state.subject_key,
            state.program,
            state.event_id,
        )
        return SubjectOutcome(
            subject_key=state.subject_key,
            program=state.program,
            record_ref=None,
            events_read=0,
            differing_fields=(),
            disposition="orphan",
        )

    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise SubjectLookupError(status_code=None, detail="a listed record carried no id")
    record_ref = f"{board.object_name}:{record_id}"

    differing = _differing_fields(record, state.fields, board)
    if not differing:
        logger.info(
            "rebuild unchanged: %s already at seq %s for subject %s program %s",
            record_ref,
            state.seq,
            state.subject_key,
            state.program,
        )
        return SubjectOutcome(
            subject_key=state.subject_key,
            program=state.program,
            record_ref=record_ref,
            events_read=0,
            differing_fields=(),
            disposition="unchanged",
        )

    # Full state, not just the differing fields: the same write the live path makes, so a rebuild
    # leaves a row in a state the incremental path could also have produced.
    client.patch_record(board.plural, record_id, state.fields)
    logger.info(
        "rebuild wrote: %s to seq %s for subject %s program %s (fields %s)",
        record_ref,
        state.seq,
        state.subject_key,
        state.program,
        ",".join(differing),
    )
    return SubjectOutcome(
        subject_key=state.subject_key,
        program=state.program,
        record_ref=record_ref,
        events_read=0,
        differing_fields=differing,
        disposition="written",
    )


def _differing_fields(
    record: Mapping[str, object],
    fields: Mapping[str, object],
    board: BoardTarget,
) -> tuple[str, ...]:
    """The names of the projected columns whose current value is not the folded one.

    Compared per column rather than by equality of the whole mapping, because two of the three
    columns have more than one faithful rendering: a DATE_TIME comes back from Twenty as UTC with
    a `Z` and milliseconds, and a NUMBER may come back as a float. Treating those as differences
    would make every rerun write, which would defeat the one property this operation sells.
    """
    differing: list[str] = []
    for name in sorted(fields):
        desired = fields[name]
        current = record.get(name)
        if name == board.as_of_field:
            same = _same_instant(current, desired)
        elif name == board.watermark_field:
            same = _as_int(current) == _as_int(desired)
        else:
            same = current == desired
        if not same:
            differing.append(name)
    return tuple(differing)


def _same_instant(current: object, desired: object) -> bool:
    """Whether two ISO-8601 renderings name the same instant. Unparseable falls back to equality."""
    left, right = _parse_instant(current), _parse_instant(desired)
    if left is None or right is None:
        return current == desired
    return left == right


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


@dataclass(frozen=True)
class RebuildConfig:
    """Everything a rebuild run holds: one Twenty credential, one replay credential, one scope."""

    target: str
    twenty_url: str
    twenty_token: str


def resolve_config(target: str, env: Mapping[str, str]) -> RebuildConfig:
    """Map a target to the rebuild's environment surface, failing once, by every missing name.

    Both facilities are checked together so an operator sees every variable they still have to set
    rather than one per run. The replay pair is only *named* here — `pulse_core.replay` owns those
    names, because the replay credential is the kit's facility and this package holds exactly one
    credential of its own (connector-kit spec, `test_connector_credential_gate.py`).

    An empty value counts as missing: an unset secret reaches a job as an empty string.
    """
    url_var, token_var = env_var_names(target)
    missing = tuple(
        name for name in (url_var, token_var, REPLAY_BASE_URL_ENV_VAR, REPLAY_TOKEN_ENV_VAR) if not env.get(name)
    )
    if missing:
        raise RebuildStartupError(missing)
    return RebuildConfig(target=target, twenty_url=env[url_var], twenty_token=env[token_var])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twenty-projection-rebuild",
        description="Repaint the Twenty board projection from the ledger's committed events.",
    )
    parser.add_argument("--scope", required=True, help="<subject_type>[:<key>], e.g. enrollment:pt-0001")
    parser.add_argument("--target", required=True, help="deployment target (dev|staging|prod)")
    parser.add_argument(
        "--operator",
        required=True,
        help="who is running this rebuild — the receipt is attributable or it is not a receipt",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client: ProjectionRestClient | None = None,
    history: HistorySource | None = None,
) -> int:
    """`task projection:rebuild`: resolve the environment by name, repaint the scope, print it.

    `client` and `history` are the two fixture seams; production passes neither and gets the real
    transports. Exit 2 for a configuration or scope failure (nothing was read or written), 1 for a
    rebuild that started and failed, 0 for a rebuild that finished.
    """
    args = _build_parser().parse_args(argv)
    environment = os.environ if env is None else env

    logging.basicConfig(level=logging.INFO)
    try:
        scope = parse_scope(args.scope)
        config = resolve_config(args.target, environment)
    except (ScopeError, RebuildStartupError) as error:
        print(f"twenty-projection rebuild refused: {error}", file=sys.stderr)
        return 2

    # Whichever transports this run owns, it closes; an injected one belongs to its caller.
    owned_client: ProjectionRestClient | None = None
    owned_history: PulseCoreClient | None = None
    if client is not None:
        active_client = client
    else:
        owned_client = ProjectionRestClient(config.twenty_url, token=config.twenty_token)
        active_client = owned_client

    active_history: HistorySource
    if history is not None:
        active_history = history
    else:
        try:
            owned_history = replay_client_from_env(environment, writer_id=PROJECTION_WRITER_ID)
        except ReplayStartupError as error:
            if owned_client is not None:
                owned_client.close()
            print(f"twenty-projection rebuild refused: {error}", file=sys.stderr)
            return 2
        active_history = owned_history

    try:
        receipt = rebuild(scope, history=active_history, client=active_client, operator=args.operator)
    except (ProjectionApplyError, ProjectionRebuildError, SubjectHistoryRefusedError) as error:
        print(f"twenty-projection rebuild failed for scope {scope.label}: {error}", file=sys.stderr)
        return 1
    finally:
        if owned_client is not None:
            owned_client.close()
        if owned_history is not None:
            owned_history.close()

    print(receipt.render())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
