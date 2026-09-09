"""The patients rebuild as an operator command: `patients` repainted from the ledger alone.

    task projection:rebuild-patients TARGET=dev OPERATOR=<who>

`handlers.patient_state.rebuild` (task 1.1) shipped with a `JournalReader` Protocol and a test
fixture — everything except something to invoke on dev. The runbook found the gap and design.md
decision 12 closed it here rather than in an adapter written on the day, which would be untested
code touching real rows. This module is the two things the handler deliberately left out: where
the events come from, and which subjects to ask about.

**Where the events come from.** `pulse_core.client.PulseCoreClient.subject_history`, over HTTP,
with the kit's `pulse_core.replay` credential — the same route and the same credential
`twenty_projection.rebuild` reads for the board. No ledger DSN, no database driver, no
`pulse_ledger` import: what this projection must never hold is a *database* credential for the
ledger, and holding one would make "the projection is a window on the journal" unfalsifiable.

**Which subjects.** The ledger's read surface is per subject — there is no "every enrollment event"
route — so the scope has to be enumerated from this side. It is every `patient_id` already in
`patients`, which is exactly the set of legacy rows waiting to be adopted (spec: "Legacy rows are
marked, never overwritten"), plus any `--subject` the operator names for a subject with no row yet.
Subjects the ledger mints after the EventBridge rule is applied arrive on the live feed and need no
rebuild. Per-subject order is enough because the monotonic guard is per `patient_id`: one subject's
events can never decide another subject's row.

**Nothing here writes.** Every mutation is `handle_patient_state`'s one statement, reached through
`rebuild()`. This module issues exactly one statement of its own, a `SELECT` of the scope. That is
not a convention — it is what makes the monotonic guard, the legacy-adoption rule and the
read-only gate (`packages/ocean/tests/gates/test_patients_read_only.py`) true of the rebuild and
not just of the live consumer.

**A subject with no history is a counted park, not a failure.** The ledger having no `enrollment`
event for a legacy row is the ordinary state of things before genesis; the row keeps its status and
its null citation. It joins the receipt's parked count, which is the same disposition the handler
gives an event it applied nothing for: counted, never silently dropped.

**Import boundary.** `pulse-core` is a graph-projection dependency *for this module only*. The live
handler imports nothing from it (design.md decision 12) — the consumer path stays a plain
ocean-events consumer, and a broken kit release cannot stop the projection from applying events.

**Log and receipt posture.** Identifiers, sequences, counts and the state name, and nothing else —
the 1.1 tripwire applies here too. The receipt is `RebuildReceipt.render()`: counts only, safe to
paste onto the tracking issue the attended run is recorded on.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Protocol

import sqlalchemy as sa
import structlog
from pulse_core.client import PulseCoreClient, SubjectHistoryRefusedError
from pulse_core.history import DEFAULT_HISTORY_PAGE_SIZE
from pulse_core.replay import (
    REPLAY_BASE_URL_ENV_VAR,
    REPLAY_TOKEN_ENV_VAR,
    ReplayStartupError,
    replay_client_from_env,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.handlers.patient_state import (
    ENROLLMENT_SUBJECT_TYPE,
    CanonicalIdResolver,
    RebuildReceipt,
    rebuild,
    resolve_canonical_patient_id,
)

log = structlog.get_logger()

#: The identity a replay read is made under. It reaches nothing on a read path (it seeds the
#: idempotency key of a *submitted* command), but no read is made anonymously.
PROJECTION_WRITER_ID = "graph-projection-patients"

#: Where the graph database this projection writes lives. The same variable the service itself
#: reads (`main.py`), so a rebuild and the running consumer cannot disagree about which database
#: `patients` is in. `TARGET` names whose credentials are loaded, not a second variable name —
#: the `relay:run` convention.
DATABASE_URL_ENV_VAR = "DATABASE_URL"

#: The one statement this module issues. A read: the scope is the rows that exist, because those
#: are the legacy rows adoption is for.
_SCOPE_SQL = sa.text("SELECT patient_id FROM patients ORDER BY patient_id")


class RebuildStartupError(RuntimeError):
    """The rebuild's environment is incomplete — names every absent variable, never a value."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"patients rebuild is not configured — set: {', '.join(missing)}")


class SubjectHistorySource(Protocol):
    """The replay surface the reader reads: one subject's committed events, in ledger sequence.

    `PulseCoreClient` satisfies it structurally, which is the point — the reader depends on the
    shape of the read rather than on the client, so a test hands it a fixture history and holds no
    credential at all.
    """

    def subject_history(
        self,
        subject_type: str,
        subject_key: str,
        *,
        page_size: int = ...,
    ) -> Sequence[Mapping[str, object]]: ...


class LedgerJournalReader:
    """A `JournalReader` (task 1.1) over the ledger's per-subject replay route.

    Yields lazily, one subject at a time, so a rebuild over a long scope never holds every event
    of every subject in memory at once — the handler applies each event as it arrives and keeps
    only counters. Paging within a subject is `subject_history`'s keyset walk on `after_seq`, run
    to exhaustion; `page_size` exists so a test can prove the walk rather than assume it.

    `subjects_without_history` is the count of subjects the ledger answered with an empty history.
    It is a fact about the run, not an error: an unset credential can never reach here as an empty
    history, because `subject_history` raises rather than returning `[]` for a read it could not
    make.
    """

    def __init__(
        self,
        *,
        history: SubjectHistorySource,
        subjects: Iterable[str],
        page_size: int = DEFAULT_HISTORY_PAGE_SIZE,
    ) -> None:
        self._history = history
        self._subjects = tuple(subjects)
        self._page_size = page_size
        self.subjects_without_history = 0

    def enrollment_events(self) -> Iterator[Mapping[str, object]]:
        for subject_key in self._subjects:
            events = self._history.subject_history(ENROLLMENT_SUBJECT_TYPE, subject_key, page_size=self._page_size)
            if not events:
                self.subjects_without_history += 1
                log.info("patient_state_rebuild_no_history", subject_key=subject_key)
                continue
            yield from events


async def resolve_scope(session, subjects: Iterable[str] = ()) -> tuple[str, ...]:
    """Every `patient_id` in `patients`, plus the operator's `--subject` list, sorted and unique.

    The table side is the adoption scope: a legacy row is only adopted when an event for its
    canonical patient id is applied, so the rows that are there are precisely the ones a rebuild
    exists to citate. The operator side is the only way to reach a subject with no row yet — the
    ledger cannot be enumerated from here, so a subject nothing has minted is invisible until
    someone names it.
    """
    result = await session.execute(_SCOPE_SQL)
    from_table = {row[0] for row in result if isinstance(row[0], str) and row[0]}
    named = {subject.strip() for subject in subjects if subject.strip()}
    return tuple(sorted(from_table | named))


async def rebuild_patients(
    session,
    *,
    history: SubjectHistorySource,
    subjects: Iterable[str] = (),
    page_size: int = DEFAULT_HISTORY_PAGE_SIZE,
    resolver: CanonicalIdResolver = resolve_canonical_patient_id,
) -> RebuildReceipt:
    """Replay the scope's committed `enrollment` events onto `patients` and receipt the run.

    Safe to rerun by construction: the guard makes a replay of already-applied events a counted run
    of skips, so a second run with no intervening events writes nothing.

    Subjects the ledger has no history for are folded into the receipt's parked count — the
    disposition they share with an event the handler applied nothing for.
    """
    scope = await resolve_scope(session, subjects)
    reader = LedgerJournalReader(history=history, subjects=scope, page_size=page_size)
    receipt = await rebuild(reader, session, resolver=resolver)
    parked = receipt.parked + reader.subjects_without_history
    log.info(
        "patient_state_rebuild_scope",
        subjects_in_scope=len(scope),
        subjects_without_history=reader.subjects_without_history,
    )
    return dataclasses.replace(receipt, parked=parked)


def resolve_config(env: Mapping[str, str]) -> str:
    """The rebuild's environment surface, checked once, failing by every missing name.

    Both facilities are checked together so an operator sees every variable they still have to set
    rather than one per run. The replay pair is only *named* here — `pulse_core.replay` owns those
    names, because the replay credential is the kit's facility. An empty value counts as missing:
    an unset secret reaches a job as an empty string.

    Returns the graph database URL; raises `RebuildStartupError` naming everything absent.
    """
    missing = tuple(
        name for name in (DATABASE_URL_ENV_VAR, REPLAY_BASE_URL_ENV_VAR, REPLAY_TOKEN_ENV_VAR) if not env.get(name)
    )
    if missing:
        raise RebuildStartupError(missing)
    return env[DATABASE_URL_ENV_VAR]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-projection-rebuild-patients",
        description="Repaint the patients projection from the ledger's committed enrollment events.",
    )
    parser.add_argument("--target", required=True, help="deployment target (dev|staging|prod)")
    parser.add_argument(
        "--operator",
        required=True,
        help="who is running this rebuild — the receipt is attributable or it is not a receipt",
    )
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        metavar="PATIENT_ID",
        help="a canonical patient id with no row yet; repeatable. Every existing row is in scope already.",
    )
    return parser


async def _run_owned(database_url: str, *, history: SubjectHistorySource, subjects: Sequence[str]) -> RebuildReceipt:
    """Open the graph database this rebuild owns, run inside one transaction, dispose of it.

    One transaction for the whole run, the same shape the consumer commits per message in: a
    rebuild that half-applied would leave a projection no single ledger position explains.
    """
    engine = create_async_engine(database_url, echo=False)
    try:
        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_maker() as session, session.begin():
            return await rebuild_patients(session, history=history, subjects=subjects)
    finally:
        await engine.dispose()


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    history: SubjectHistorySource | None = None,
    session: object | None = None,
) -> int:
    """`task projection:rebuild-patients`: resolve the environment, repaint the scope, print it.

    `history` and `session` are the two fixture seams; production passes neither and gets the real
    transports. Exit 2 for a configuration failure (nothing was read or written), 1 for a rebuild
    that started and failed, 0 for a rebuild that finished.
    """
    args = _build_parser().parse_args(argv)
    environment = os.environ if env is None else env

    try:
        database_url = resolve_config(environment)
    except RebuildStartupError as error:
        print(f"patients rebuild refused: {error}", file=sys.stderr)
        return 2

    # Attribution and target are stated once, in one line, before anything is read: a rebuild that
    # cannot say who ran it against which environment is not a receipt.
    log.info("patient_state_rebuild_started", target=args.target, operator=args.operator)

    owned_history: PulseCoreClient | None = None
    if history is not None:
        active_history = history
    else:
        try:
            owned_history = replay_client_from_env(environment, writer_id=PROJECTION_WRITER_ID)
        except ReplayStartupError as error:
            print(f"patients rebuild refused: {error}", file=sys.stderr)
            return 2
        active_history = owned_history

    try:
        if session is None:
            receipt = asyncio.run(_run_owned(database_url, history=active_history, subjects=args.subject))
        else:
            receipt = asyncio.run(rebuild_patients(session, history=active_history, subjects=args.subject))
    except SubjectHistoryRefusedError as error:
        print(f"patients rebuild failed for operator {args.operator}: {error}", file=sys.stderr)
        return 1
    finally:
        if owned_history is not None:
            owned_history.close()

    print(receipt.render())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
