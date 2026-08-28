"""Orphan parking and payload-free failure handling around the apply core (task 2.2).

`handle_event` is what the consumer loop (task 2.3) calls per message. It adds exactly two
behaviors to `apply_event`, both spec-owned:

- **Orphans park.** A subject with no board record completes as `Parked` — one counted metric,
  one log line carrying the subject key and event id only — and never crashes the consumer or
  blocks the queue. The parked event is dropped from the projection's point of view;
  convergence is restored by the subject's next event once the record exists (full-state
  writes, design decision 3).
- **Failed writes retry, then surface payload-free.** The retry posture mirrors
  `pulse_ledger.twenty.client`: only what retrying can fix (5xx and transport failures), capped
  exponential backoff, injectable sleeper. Exhausted or non-retryable failures re-raise
  `ProjectionWriteError` after one identifiers-only log line, so the consumer never deletes the
  message and redelivery gets another chance. Nothing here reads a response body: every logged
  string is built from envelope identifiers and the typed error's own fields, so a failure body
  cannot reach a log line or a metric.

Retrying re-runs the whole apply — lookup included — which is safe by construction: the write
is full-state and watermark-guarded, and a refreshed watermark on retry only ever turns a
would-be write into a no-op.

Everything else (`MalformedEventError`, `AmbiguousSubjectError`, `SubjectLookupError`)
propagates untouched: those are data or transport faults the consumer must surface, not park.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from twenty_projection.apply import (
    V1_BOARD,
    ApplyResult,
    BoardTarget,
    ProjectionRestClient,
    ProjectionWriteError,
    SubjectUnresolvedError,
    apply_event,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0

Sleeper = Callable[[float], None]


class ProjectionMetrics:
    """In-process counters, and only counters — a payload value has nothing to ride in on.

    The consumer (task 2.3) owns emitting these; the handling layer only increments.
    """

    def __init__(self) -> None:
        self.orphans_parked = 0
        self.write_failures = 0


@dataclass(frozen=True)
class Parked:
    """An orphan event, parked: no board record for its subject, counted and logged, done."""

    subject_key: str
    program: str
    event_id: str


HandleResult = ApplyResult | Parked


def handle_event(
    envelope: Mapping[str, object],
    *,
    client: ProjectionRestClient,
    metrics: ProjectionMetrics,
    board: BoardTarget = V1_BOARD,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    sleep: Sleeper = time.sleep,
) -> HandleResult:
    """Apply one event with the consumer-facing failure posture.

    Returns the apply core's own results, or `Parked` for an unresolvable subject. Raises
    `ProjectionWriteError` once retries are exhausted (or immediately for a non-retryable
    status), after counting and logging it — identifiers only, never payload content.
    """
    if max_attempts < 1:
        msg = "max_attempts must be at least 1"
        raise ValueError(msg)
    event_id = _envelope_id(envelope)

    attempt = 0
    while True:
        attempt += 1
        try:
            return apply_event(envelope, client=client, board=board)
        except SubjectUnresolvedError as orphan:
            metrics.orphans_parked += 1
            logger.warning(
                "projection orphan parked: no board record for subject %s (event %s)",
                orphan.subject_key,
                event_id,
            )
            return Parked(subject_key=orphan.subject_key, program=orphan.program, event_id=event_id)
        except ProjectionWriteError as failure:
            retryable = failure.status_code is None or failure.status_code >= 500
            if retryable and attempt < max_attempts:
                logger.warning(
                    "projection write failed, retrying (attempt %s/%s, event %s): %s",
                    attempt,
                    max_attempts,
                    event_id,
                    failure,
                )
                sleep(_backoff_delay(attempt, base=base_delay_seconds, maximum=max_delay_seconds))
                continue
            metrics.write_failures += 1
            # `exception` over `error` (TRY400): the traceback carries code locations only —
            # the failure body was dropped unread by `patch_record`, so it cannot appear here.
            logger.exception(
                "projection write failed for good after %s attempt(s) (event %s)",
                attempt,
                event_id,
            )
            raise


def _envelope_id(envelope: Mapping[str, object]) -> str:
    """The event id for log lines, tolerant of a malformed envelope (apply validates it)."""
    value = envelope.get("event_id")
    return value if isinstance(value, str) and value else "<no event id>"


def _backoff_delay(attempt: int, *, base: float, maximum: float) -> float:
    """Exponential backoff, capped: attempt 1 waits `base`, attempt 2 waits `2*base`, ..."""
    delay = base * (2 ** (attempt - 1))
    return delay if delay < maximum else maximum
