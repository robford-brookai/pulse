"""`pulse_core.client` — response classification, retry-on-transient, and `consume(handler)`.

The command API is faked at the client boundary (`httpx.MockTransport`, a fake SQS client) rather
than exercised live, per this change's testing posture. No live network in any test.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from pulse_core.client import (
    ConsumeReport,
    InMemoryDeduper,
    PulseCoreClient,
    ResponseClassification,
    UnexpectedResponseError,
    classify_response,
    consume,
    consume_once,
)
from pulse_core.generated import DeclareTransitionCommand, DeclareVerdictCommand, VerdictOutcome

T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _client(handler, **kwargs) -> PulseCoreClient:
    transport = httpx.MockTransport(handler)
    return PulseCoreClient(
        "http://ledger.test",
        writer_id="verdict-relay",
        token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
        transport=transport,
        sleep=lambda _seconds: None,
        **kwargs,
    )


class TestClassifyResponse:
    def test_a_fresh_commit_is_committed(self) -> None:
        response = httpx.Response(
            201,
            json={"event_id": "e1", "recorded_at": "2026-08-01T12:00:00+00:00", "rule_version": "v0.7"},
            request=httpx.Request("POST", "http://x/commands"),
        )
        result = classify_response(response)
        assert result.classification is ResponseClassification.COMMITTED
        assert result.event_id == "e1"
        assert result.is_success

    def test_a_repeated_idempotency_key_is_replayed(self) -> None:
        response = httpx.Response(
            201,
            json={"event_id": "e1", "replayed": True},
            request=httpx.Request("POST", "http://x/commands"),
        )
        result = classify_response(response)
        assert result.classification is ResponseClassification.REPLAYED
        assert result.event_id == "e1"
        assert result.is_success

    def test_a_catalog_rejection_carries_the_reason_and_version(self) -> None:
        response = httpx.Response(
            422,
            json={
                "detail": {
                    "message": "not a legal transition",
                    "reason": "illegal transition",
                    "catalog_version": "appendix-c-v0.7",
                }
            },
            request=httpx.Request("POST", "http://x/commands"),
        )
        result = classify_response(response)
        assert result.classification is ResponseClassification.REJECTED
        assert not result.is_success
        assert result.rejection is not None
        assert result.rejection.reason == "illegal transition"
        assert result.rejection.catalog_version == "appendix-c-v0.7"

    def test_an_auth_rejection_classifies_the_same_as_a_catalog_one(self) -> None:
        response = httpx.Response(
            403,
            json={"detail": {"message": "spoofed actor"}},
            request=httpx.Request("POST", "http://x/commands"),
        )
        result = classify_response(response)
        assert result.classification is ResponseClassification.REJECTED

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_server_trouble_is_transient(self, status: int) -> None:
        response = httpx.Response(status, text="upstream unwell", request=httpx.Request("POST", "http://x/commands"))
        result = classify_response(response)
        assert result.classification is ResponseClassification.TRANSIENT

    def test_an_unrecognised_status_raises_rather_than_guessing(self) -> None:
        response = httpx.Response(418, text="teapot", request=httpx.Request("POST", "http://x/commands"))
        with pytest.raises(UnexpectedResponseError):
            classify_response(response)

    def test_a_non_json_success_body_still_classifies_committed(self) -> None:
        response = httpx.Response(201, text="not json", request=httpx.Request("POST", "http://x/commands"))
        result = classify_response(response)
        assert result.classification is ResponseClassification.COMMITTED
        assert result.event_id is None


class TestSubmitCommand:
    def test_a_legal_transition_commits(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["subject_type"] == "enrollment"
            assert body["subject_key"] == "enr-1"
            assert body["event_type"] == "declare_transition"
            assert body["to_state"] == "on_hold"
            assert body["payload"] == {"reason": "member request"}
            assert "idempotency_key" in body
            assert request.headers["authorization"] == "Bearer unit-test-token"
            return httpx.Response(
                201,
                json={"event_id": "e1", "recorded_at": "2026-08-01T12:00:00+00:00", "rule_version": "v0.7"},
                request=request,
            )

        client = _client(handler)
        command = DeclareTransitionCommand(
            subject_key="enr-1", subject_type="enrollment", to_state="on_hold", reason="member request"
        )
        result = client.submit_command(command, effective_at=T0)
        assert result.classification is ResponseClassification.COMMITTED
        assert result.event_id == "e1"

    def test_the_idempotency_key_is_stable_for_the_same_command_and_logical_time(self) -> None:
        seen_keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_keys.append(json.loads(request.content)["idempotency_key"])
            return httpx.Response(201, json={"event_id": "e1"}, request=request)

        client = _client(handler)
        command = DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold")
        client.submit_command(command, effective_at=T0)
        client.submit_command(command, effective_at=T0)
        assert seen_keys[0] == seen_keys[1]
        assert seen_keys[0].startswith("verdict-relay:")

    def test_a_different_logical_time_derives_a_different_key(self) -> None:
        seen_keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_keys.append(json.loads(request.content)["idempotency_key"])
            return httpx.Response(201, json={"event_id": "e1"}, request=request)

        client = _client(handler)
        command = DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold")
        client.submit_command(command, effective_at=T0)
        client.submit_command(command, effective_at=T0.replace(hour=13))
        assert seen_keys[0] != seen_keys[1]

    def test_an_illegal_transition_is_rejected_without_retry(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                422,
                json={"detail": {"message": "no", "reason": "illegal transition", "catalog_version": "v0.7"}},
                request=request,
            )

        client = _client(handler)
        command = DeclareTransitionCommand(subject_key="be-1", subject_type="billing_episode", to_state="qualified")
        result = client.submit_command(command, effective_at=T0)
        assert result.classification is ResponseClassification.REJECTED
        assert calls == 1

    def test_a_verdict_with_indeterminate_outcome_requires_a_reason_before_the_wire(self) -> None:
        with pytest.raises(ValueError):
            DeclareVerdictCommand(
                subject_key="be-1",
                subject_type="billing_episode",
                outcome=VerdictOutcome.INDETERMINATE,
                rule_version="v0.7",
                as_of=T0,
            )

    def test_a_transient_failure_retries_and_eventually_commits(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, text="db failover", request=request)
            return httpx.Response(201, json={"event_id": "e1"}, request=request)

        client = _client(handler, max_attempts=5)
        command = DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold")
        result = client.submit_command(command, effective_at=T0)
        assert result.classification is ResponseClassification.COMMITTED
        assert attempts == 3
        assert result.attempts == 3

    def test_a_persistent_transient_failure_gives_up_after_max_attempts(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, text="db failover", request=request)

        client = _client(handler, max_attempts=3)
        command = DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold")
        result = client.submit_command(command, effective_at=T0)
        assert result.classification is ResponseClassification.TRANSIENT
        assert attempts == 3
        assert result.attempts == 3

    def test_a_network_failure_classifies_transient_and_retries(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise httpx.ConnectError("refused", request=request)
            return httpx.Response(201, json={"event_id": "e1"}, request=request)

        client = _client(handler, max_attempts=5)
        command = DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold")
        result = client.submit_command(command, effective_at=T0)
        assert result.classification is ResponseClassification.COMMITTED
        assert attempts == 2

    def test_the_backoff_sleeps_between_attempts_not_after_the_last_one(self) -> None:
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down", request=request)

        client = PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(handler),
            sleep=sleeps.append,
            max_attempts=3,
        )
        command = DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold")
        client.submit_command(command, effective_at=T0)
        assert len(sleeps) == 2
        assert sleeps[1] > sleeps[0]


class TestConsume:
    def _sqs_client(self, messages: list[dict]):
        deleted: list[str] = []

        class FakeSqs:
            def receive_message(self, **kwargs):
                pending = [m for m in messages if m["ReceiptHandle"] not in deleted]
                return {"Messages": pending}

            def delete_message(self, *, QueueUrl, ReceiptHandle):
                deleted.append(ReceiptHandle)

        return FakeSqs(), deleted

    def _message(self, receipt: str, event_id: str, **payload) -> dict:
        return {
            "ReceiptHandle": receipt,
            "Body": json.dumps({"event_id": event_id, "event_type": "declare_transition", "payload": payload}),
        }

    def test_a_message_is_processed_and_deleted(self) -> None:
        handled: list[dict] = []
        messages = [self._message("r1", "evt-1")]
        sqs, deleted = self._sqs_client(messages)

        report = consume_once(handled.append, sqs_client=sqs, queue_url="q", deduper=InMemoryDeduper())

        assert report == ConsumeReport(processed=1, deduped=0, failed=0)
        assert [envelope["event_id"] for envelope in handled] == ["evt-1"]
        assert deleted == ["r1"]

    def test_redelivery_of_the_same_event_id_is_deduped_and_the_handler_runs_once(self) -> None:
        handled: list[dict] = []
        deduper = InMemoryDeduper()
        message = self._message("r1", "evt-1")

        class RedeliveringSqs:
            def __init__(self) -> None:
                self.deletes = 0

            def receive_message(self, **kwargs):
                # The same message is redelivered every pass, as SQS does until it is deleted.
                return {"Messages": [message]}

            def delete_message(self, *, QueueUrl, ReceiptHandle):
                self.deletes += 1

        sqs = RedeliveringSqs()
        consume_once(handled.append, sqs_client=sqs, queue_url="q", deduper=deduper)
        report = consume_once(handled.append, sqs_client=sqs, queue_url="q", deduper=deduper)

        assert len(handled) == 1
        assert report == ConsumeReport(processed=0, deduped=1, failed=0)
        assert sqs.deletes == 2

    def test_a_failing_handler_leaves_the_message_undeleted_for_redelivery(self) -> None:
        def failing_handler(envelope: dict) -> None:
            raise RuntimeError("boom")

        messages = [self._message("r1", "evt-1")]
        sqs, deleted = self._sqs_client(messages)

        report = consume_once(failing_handler, sqs_client=sqs, queue_url="q", deduper=InMemoryDeduper())

        assert report == ConsumeReport(processed=0, deduped=0, failed=1)
        assert deleted == []

    def test_a_malformed_message_is_dropped_not_retried_forever(self) -> None:
        handled: list[dict] = []
        messages = [{"ReceiptHandle": "r1", "Body": "not json"}]
        sqs, _deleted = self._sqs_client(messages)

        report = consume_once(handled.append, sqs_client=sqs, queue_url="q", deduper=InMemoryDeduper())

        assert report.failed == 1
        assert handled == []

    def test_an_eventbridge_wrapped_envelope_is_unwrapped(self) -> None:
        handled: list[dict] = []
        wrapped = {"ReceiptHandle": "r1", "Body": json.dumps({"detail": {"event_id": "evt-9"}})}
        sqs, _deleted = self._sqs_client([wrapped])

        consume_once(handled.append, sqs_client=sqs, queue_url="q", deduper=InMemoryDeduper())

        assert handled == [{"event_id": "evt-9"}]

    def test_consume_loops_for_the_given_number_of_iterations(self) -> None:
        handled: list[dict] = []
        messages = [self._message("r1", "evt-1")]
        sqs, _deleted = self._sqs_client(messages)

        consume(handled.append, queue_url="q", sqs_client=sqs, iterations=3)

        # Deleted after the first pass, so only one iteration finds anything to process.
        assert len(handled) == 1

    def test_consume_backs_off_after_a_receive_failure_instead_of_spinning(self) -> None:
        sleeps: list[float] = []

        class FailingSqs:
            def receive_message(self, **kwargs):
                raise RuntimeError("unavailable")

        consume(
            lambda envelope: None,
            queue_url="q",
            sqs_client=FailingSqs(),
            iterations=2,
            sleep=sleeps.append,
            error_backoff_seconds=1.5,
        )

        assert sleeps == [1.5, 1.5]
