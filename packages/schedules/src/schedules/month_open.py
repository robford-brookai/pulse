"""`schedules.month_open` — declare one `open_billing_episode` per active/on-hold Enrollment.

Task 2.1's scope, per the month-open spec's "Normal month-open" and "A state-name typo rejects
the run" scenarios: enumerate the eligible Enrollment set through the ledger's own current-state
read surface — never the warehouse — build one `open_billing_episode` command per enrollment x
current month with a D16 idempotency key, and submit through the command-API client boundary.
Re-run correctness (task 2.2) and the zero-enrollment invariant plus receipt (task 2.3) build on
`declare_month_open` below without changing its shape.

Two boundaries this module never crosses directly (design decision 9):

- **The ledger read.** `EnrollmentSource` abstracts where current-state Enrollment rows come from.
  `LedgerEnrollmentSource` is the production implementation — a thin wrapper over
  `pulse_ledger.reads.enumerate_state`, a library read against the ledger's own co-committed
  `current_state` rows, not the warehouse. Catalog validation happens inside `enumerate_state`
  itself, before any query runs: an unknown state name in `states` raises `IllegalTransitionError`
  with zero rows read and, because enumeration happens before any submission below, zero commands
  declared. Every test uses `FixtureEnrollmentSource` over recorded rows instead.
- **The command API.** Submission goes through `pulse_core.client.PulseCoreClient.submit_command`,
  which derives the D16 idempotency key client-side and classifies the response
  (`committed | replayed | rejected | transient`); every test fakes this at the `httpx` transport
  boundary, per the package's `--disable-socket` posture.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

import psycopg
from pulse_core.client import CommandResponse, PulseCoreClient
from pulse_core.generated import OpenBillingEpisodeCommand
from pulse_ledger.reads import SubjectState, enumerate_state

#: The subject type month-open enumerates. Fixed — this job has exactly one input subject.
ENROLLMENT_SUBJECT_TYPE = "enrollment"

#: The subject type `open_billing_episode` declares against (pinned by the generated command
#: type itself; restated here for readers of this module).
BILLING_EPISODE_SUBJECT_TYPE = "billing_episode"

#: The Enrollment states month-open bills for (spec: "Month-open opens one BillingEpisode per
#: eligible enrollment"). `ended` enrollments, and any other state the catalog defines, are
#: excluded by never being in this set — not by a post-filter over a wider read.
ELIGIBLE_ENROLLMENT_STATES: tuple[str, ...] = ("active", "on_hold")


def billing_episode_subject_key(enrollment_key: str, month: date) -> str:
    """The `billing_episode` subject_key for one enrollment x month — the object model's own grain
    (BillingEpisode = enrollment x calendar month, rpc-object-model-assessment.md Appendix C).
    """
    return f"{enrollment_key}:{month.isoformat()}"


def billing_month_effective_at(month: date) -> datetime:
    """The D16 `effective_at` (and therefore `logical_time`) for one billing month's declarations.

    Midnight UTC on the first of `month` — never "now" — so every declaration for the same
    enrollment x month derives the same idempotency key regardless of what day or time of day the
    job happens to run (design decision 3; re-run correctness is task 2.2's scenario, but the key
    must already be stable from this task on).
    """
    return datetime(month.year, month.month, 1, tzinfo=timezone.utc)


class EnrollmentSource(Protocol):
    """Where current-state Enrollment rows come from: the ledger's read surface in production, a
    recorded fixture in every test (design decision 9)."""

    def eligible(self, states: Sequence[str]) -> Sequence[SubjectState]: ...


@dataclass(frozen=True)
class LedgerEnrollmentSource:
    """The production `EnrollmentSource`: `pulse_ledger.reads.enumerate_state` over a live
    connection to the ledger's own Postgres — never the warehouse or any projection.
    """

    conn: psycopg.Connection

    def eligible(self, states: Sequence[str]) -> Sequence[SubjectState]:
        return enumerate_state(self.conn, ENROLLMENT_SUBJECT_TYPE, states)


@dataclass(frozen=True)
class FixtureEnrollmentSource:
    """An `EnrollmentSource` over recorded enumeration rows — every test's implementation.

    `rows` stands in for a recorded `enumerate_state` response: `eligible` filters it to the
    requested `states`, the same narrowing the real query does server-side, so a test can hold one
    fixture covering several states (as the "Normal month-open" scenario's ledger does) and assert
    on exactly which states a run asked for.
    """

    rows: Sequence[SubjectState]

    def eligible(self, states: Sequence[str]) -> Sequence[SubjectState]:
        wanted = set(states)
        return [row for row in self.rows if row.state in wanted]


def build_open_billing_episode_command(enrollment: SubjectState, month: date) -> OpenBillingEpisodeCommand:
    """One `open_billing_episode` command for one enrollment's current-month episode."""
    return OpenBillingEpisodeCommand(
        subject_key=billing_episode_subject_key(enrollment.subject_key, month),
        month=month,
    )


@dataclass(frozen=True)
class MonthOpenDeclaration:
    """One enrollment's command and the client's classified response.

    The run's receipt (task 2.3) is a tally over these; this task returns them uninterpreted.
    """

    enrollment: SubjectState
    command: OpenBillingEpisodeCommand
    response: CommandResponse


def declare_month_open(
    source: EnrollmentSource,
    client: PulseCoreClient,
    *,
    month: date,
    states: Sequence[str] = ELIGIBLE_ENROLLMENT_STATES,
) -> list[MonthOpenDeclaration]:
    """Enumerate eligible Enrollments and declare one `open_billing_episode` each for `month`.

    Enumeration happens before any submission: `source.eligible` validates `states` against the
    catalog before returning a row (in production, inside `enumerate_state`), so an unknown state
    name propagates its rejection with zero commands declared (spec: "A state-name typo rejects
    the run") rather than an empty result read as "nothing to bill this month". Declarations
    happen in the enumeration's own order — `subject_key` order for the ledger read.
    """
    enrollments = source.eligible(states)
    effective_at = billing_month_effective_at(month)
    declarations: list[MonthOpenDeclaration] = []
    for enrollment in enrollments:
        command = build_open_billing_episode_command(enrollment, month)
        response = client.submit_command(command, effective_at=effective_at)
        declarations.append(MonthOpenDeclaration(enrollment=enrollment, command=command, response=response))
    return declarations
