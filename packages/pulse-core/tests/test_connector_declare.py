"""`pulse_core.connector.declare` — the declare pipeline extracted from `verdict_relay.declarer`
(task 2.2).

Covers the connector-kit spec's declare-pipeline scenario: "A rerun declares nothing twice" — a
batch fully declared by a prior run has every resubmission classify as `replayed`, never a second
`committed`, and the receipt counts the replays. The retry/backoff loop and its exhaustion are
tested directly against a scripted sequence of classifications; no HTTP, no ledger.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pulse_core.client import CommandResponse, Rejection, ResponseClassification
from pulse_core.connector.declare import (
    DeclareCounts,
    TransientExhaustedError,
    backoff_delay,
    submit_with_retry,
)


def _response(classification: ResponseClassification, *, detail: str | None = None) -> CommandResponse:
    rejection = Rejection(message=detail) if detail is not None else None
    return CommandResponse(classification=classification, status_code=None, rejection=rejection)


@dataclass
class ScriptedSubmit:
    """A `submit` callable answering one scripted classification per call; the last repeats."""

    responses: list[CommandResponse]
    calls: int = 0

    def __call__(self) -> CommandResponse:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class TestRerunDeclaresNothingTwice:
    """Scenario: a batch fully declared by a prior run resubmits and only replays."""

    def test_a_resubmitted_committed_fact_classifies_as_replayed_not_committed_again(self) -> None:
        counts = DeclareCounts()
        first = submit_with_retry(
            ScriptedSubmit([_response(ResponseClassification.COMMITTED)]),
            ref="fact-1",
            sleep=lambda _s: None,
            jitter=lambda: 0.0,
        )
        counts = counts.record(first.classification)

        # The rerun derives the same D16 key; the ledger can only answer with a replay.
        rerun = submit_with_retry(
            ScriptedSubmit([_response(ResponseClassification.REPLAYED)]),
            ref="fact-1",
            sleep=lambda _s: None,
            jitter=lambda: 0.0,
        )
        counts = counts.record(rerun.classification)

        assert counts.committed == 1  # no new event on the rerun
        assert counts.replayed == 1  # the rerun is counted, distinctly

    def test_repeated_reruns_never_add_a_second_commit(self) -> None:
        counts = DeclareCounts()
        for _ in range(5):
            response = submit_with_retry(
                ScriptedSubmit([_response(ResponseClassification.REPLAYED)]),
                ref="fact-1",
                sleep=lambda _s: None,
                jitter=lambda: 0.0,
            )
            counts = counts.record(response.classification)

        assert counts.committed == 0
        assert counts.replayed == 5


class TestSubmitWithRetry:
    """Retry only a `transient` classification, up to the attempt budget."""

    def test_transient_then_committed_recovers_within_the_budget(self) -> None:
        submit = ScriptedSubmit([
            _response(ResponseClassification.TRANSIENT),
            _response(ResponseClassification.TRANSIENT),
            _response(ResponseClassification.COMMITTED),
        ])
        sleeps: list[float] = []

        response = submit_with_retry(
            submit,
            ref="fact-1",
            max_attempts=5,
            sleep=sleeps.append,
            jitter=lambda: 1.0,
        )

        assert response.classification is ResponseClassification.COMMITTED
        assert submit.calls == 3
        assert sleeps == [0.5, 1.0]

    def test_a_rejected_response_returns_immediately_without_retry(self) -> None:
        submit = ScriptedSubmit([_response(ResponseClassification.REJECTED, detail="illegal transition")])

        response = submit_with_retry(submit, ref="fact-1", sleep=lambda _s: None, jitter=lambda: 0.0)

        assert response.classification is ResponseClassification.REJECTED
        assert submit.calls == 1

    def test_exhausting_the_budget_raises_naming_the_ref(self) -> None:
        submit = ScriptedSubmit([_response(ResponseClassification.TRANSIENT, detail="upstream unavailable")])

        with pytest.raises(TransientExhaustedError) as excinfo:
            submit_with_retry(submit, ref="fact-1", max_attempts=3, sleep=lambda _s: None, jitter=lambda: 0.0)

        assert submit.calls == 3
        assert excinfo.value.ref == "fact-1"
        assert excinfo.value.attempts == 3
        assert "fact-1" in str(excinfo.value)
        assert "upstream unavailable" in str(excinfo.value)

    def test_backoff_is_exponential_and_capped(self) -> None:
        assert backoff_delay(1, base=0.5, maximum=30.0) == 0.5
        assert backoff_delay(2, base=0.5, maximum=30.0) == 1.0
        assert backoff_delay(3, base=0.5, maximum=30.0) == 2.0
        assert backoff_delay(10, base=0.5, maximum=30.0) == 30.0  # capped, not 256.0

    def test_max_attempts_below_one_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            submit_with_retry(
                ScriptedSubmit([]),
                ref="fact-1",
                max_attempts=0,
                sleep=lambda _s: None,
                jitter=lambda: 0.0,
            )


class TestDeclareCounts:
    def test_record_is_immutable(self) -> None:
        counts = DeclareCounts()
        updated = counts.record(ResponseClassification.COMMITTED)

        assert counts.committed == 0  # the original is untouched
        assert updated.committed == 1

    def test_transient_is_not_a_settled_disposition(self) -> None:
        with pytest.raises(ValueError, match="transient"):
            DeclareCounts().record(ResponseClassification.TRANSIENT)
