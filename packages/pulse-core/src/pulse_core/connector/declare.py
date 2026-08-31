"""Declare pipeline — the kit half every connector's writer stands on.

D16 idempotency-key derivation and response classification already live in
`pulse_core.idempotency` and `pulse_core.client` (`derive_idempotency_key`,
`ResponseClassification`, `PulseCoreClient.submit_command`) — every connector already shares
them by going through `PulseCoreClient`. What was still a private copy in
`verdict_relay.declarer` (connector-kit spec: "the kit has no behavior that is not already
proven by a shipped integration") is the retry orchestration layered *above* a client pinned to
`max_attempts=1`: transient-only retry with jittered exponential backoff, exhausting into a
failure that names the submission (design decision 4, verdict-relay: retry policy belongs to the
caller, not the client, so nothing retries twice) — and the counted receipt every run settles
into. Both extract here, unchanged in behavior.

`submit_with_retry` owns the retry loop: call `submit()` until it answers something other than
`transient`, or the attempt budget is spent — at which point `TransientExhaustedError` names the
submission's own `ref` (a caller-supplied string; verdict-relay names a row by its keys, a future
connector names whatever its own unit of submission is).

`DeclareCounts` is the receipt's core: `committed`, `replayed`, `rejected` — the three settled
outcomes a submission can land in once retry is exhausted or a non-transient classification comes
back (`transient` never reaches `record`; `submit_with_retry` only returns once it has resolved to
one of the other three, or raised). A connector's own receipt is free to carry more dispositions
(stale-skips, paired side effects); those aren't the kit's concern, this tally is — and it is why a
rerun of an already-declared batch counts every submission as `replayed` and never `committed`
(connector-kit spec: "A rerun declares nothing twice") — `record` never adds to `committed` for a
`replayed` classification, however many times the same fact is resubmitted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from pulse_core.client import CommandResponse, ResponseClassification

Sleeper = Callable[[float], None]

#: Returns a jitter factor in [0, 1]; the backoff delay is scaled by it. Injectable so tests pin
#: the schedule.
Jitter = Callable[[], float]

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 30.0


class TransientExhaustedError(RuntimeError):
    """Every attempt classified transient; the caller's budget is spent.

    Names `ref` — whatever the caller uses to identify the submission (never its content) — and
    the detail the ledger last gave, so the failure is diagnosable without an API call.
    """

    def __init__(self, ref: str, attempts: int, detail: str) -> None:
        self.ref = ref
        self.attempts = attempts
        self.detail = detail
        super().__init__(f"{ref} failed after {attempts} transient attempts: {detail}")


def backoff_delay(attempt: int, *, base: float, maximum: float) -> float:
    """Exponential ceiling for one attempt (1-indexed); the caller scales it by its own jitter."""
    ceiling = base * (2.0 ** (attempt - 1))
    return min(ceiling, maximum)


def submit_with_retry(
    submit: Callable[[], CommandResponse],
    *,
    ref: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    sleep: Sleeper,
    jitter: Jitter,
) -> CommandResponse:
    """Call `submit()` until it settles or the attempt budget is spent.

    Retries only a `transient` classification; `committed`, `replayed`, and `rejected` all return
    on the attempt that produced them. Raises `TransientExhaustedError` naming `ref` once
    `max_attempts` transient answers have been spent — the caller's own submit callable is what
    talks to `PulseCoreClient`, so this loop never touches HTTP directly.
    """
    if max_attempts < 1:
        msg = "max_attempts must be at least 1"
        raise ValueError(msg)
    response: CommandResponse | None = None
    for attempt in range(1, max_attempts + 1):
        response = submit()
        if response.classification is not ResponseClassification.TRANSIENT:
            return response
        if attempt < max_attempts:
            sleep(backoff_delay(attempt, base=base_delay_seconds, maximum=max_delay_seconds) * jitter())
    assert response is not None  # noqa: S101 — max_attempts >= 1 guarantees one submission
    detail = response.rejection.message if response.rejection else "transient"
    raise TransientExhaustedError(ref, max_attempts, detail)


@dataclass(frozen=True)
class DeclareCounts:
    """The three-count core of every connector's receipt: committed, replayed, rejected."""

    committed: int = 0
    replayed: int = 0
    rejected: int = 0

    def record(self, classification: ResponseClassification) -> DeclareCounts:
        """The next tally after one settled response — never mutates this one.

        `transient` is not a settled disposition (`submit_with_retry` never returns it) and
        raises rather than being silently folded into one of the three counts.
        """
        if classification is ResponseClassification.COMMITTED:
            return replace(self, committed=self.committed + 1)
        if classification is ResponseClassification.REPLAYED:
            return replace(self, replayed=self.replayed + 1)
        if classification is ResponseClassification.REJECTED:
            return replace(self, rejected=self.rejected + 1)
        msg = f"transient is not a settled disposition: {classification}"
        raise ValueError(msg)
