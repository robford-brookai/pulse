"""Coverage's no-payer-in-logs regression pin (task 2.3, billing-state).

The mart contract (`CONTRACT_COLUMNS`) carries no dedicated payer or member-id column — a
coverage row's only identifying field is `subject_id`, the patient x payer subject key. That key
convention is what keeps a payer identifier out of a log line at all: `Declarer` logs only
`_row_ref` (subject key, verdict type, `as_of`) plus the ledger's own rejection message, never a
row's `reason`/`outcome`/`lineage_ref` — the fields a real mart could carry a payer or member
value in (coverage-state spec: "Payer identifiers, member ids, and any coverage payload value
SHALL never appear in logs, receipts, metrics, or error messages").

This suite scripts a synthetic payer-shaped value into exactly those fields and proves it never
reaches a log line, for both a rejected verdict and a rejected paired transition — the two log
call sites `verdict_relay.declarer` owns.
"""

from __future__ import annotations

import json
import logging
from typing import cast

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT, TRANSITION_BY_OUTCOME
from verdict_relay.declarer import Declarer

#: Stands in for a raw payer/member identifier a mart could (incorrectly) place in a free-form
#: column. Distinctive enough that its presence in captured logs is unambiguous.
SYNTHETIC_PAYER_VALUE = "PAYER-SYN-99887766-MEMBER-000111222"


def coverage_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "subject_id": "coverage-4001",
        "verdict_type": "coverage_eligibility",
        "outcome": "positive",
        "reason": SYNTHETIC_PAYER_VALUE,
        "rule_version": "eligibility-270271-v1",
        "as_of": "2026-08-01T00:00:00+00:00",
        "lineage_ref": SYNTHETIC_PAYER_VALUE,
        "computed_at": "2026-08-01T02:00:00+00:00",
    }
    row.update(overrides)
    return row


def rejected_response() -> httpx.Response:
    return httpx.Response(
        422,
        json={
            "detail": {
                "message": "verdict regresses the subject's state",
                "reason": "illegal transition",
                "catalog_version": "appendix-c-v0.7",
            }
        },
    )


def committed_response(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


class ScriptedApi:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


def shipped_declarer(api: ScriptedApi) -> Declarer:
    return Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        transition_by_outcome=TRANSITION_BY_OUTCOME,
        sleep=lambda _s: None,
        jitter=lambda: 0.0,
    )


class TestNoPayerValueInLogsOnVerdictRejection:
    """Scenario: a failure log carries no payer value (verdict half rejected)."""

    def test_a_rejected_coverage_verdict_logs_the_subject_key_and_never_the_payer_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        api = ScriptedApi([rejected_response()])
        declarer = shipped_declarer(api)

        with caplog.at_level(logging.WARNING, logger="verdict_relay.declarer"):
            declarer.declare(coverage_row())

        assert declarer.counts.rejected == 1
        output = "\n".join(record.getMessage() for record in caplog.records)
        assert "coverage-4001" in output  # the subject key
        assert SYNTHETIC_PAYER_VALUE not in output


class TestNoPayerValueInLogsOnTransitionRejection:
    """Scenario: a failure log carries no payer value (paired transition rejected)."""

    def test_a_rejected_paired_transition_logs_the_subject_key_and_never_the_payer_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        api = ScriptedApi([committed_response("e1"), rejected_response()])
        declarer = shipped_declarer(api)

        with caplog.at_level(logging.WARNING, logger="verdict_relay.declarer"):
            declarer.declare(coverage_row())

        assert declarer.counts.transition_rejected == 1
        output = "\n".join(record.getMessage() for record in caplog.records)
        assert "coverage-4001" in output
        assert SYNTHETIC_PAYER_VALUE not in output
