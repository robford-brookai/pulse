"""Tests for the SQS consumer module."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from src.sqs_consumer import sqs_consumer_loop


def _make_sqs_message(body: dict, receipt_handle: str = "rh-1") -> dict:
    """Build an SQS message dict."""
    return {
        "Body": json.dumps(body),
        "ReceiptHandle": receipt_handle,
    }


def _wrap_in_sns_envelope(payload: dict) -> dict:
    """Wrap an Impilo payload in an SNS envelope."""
    return {
        "Type": "Notification",
        "Message": json.dumps(payload),
        "TopicArn": "arn:aws:sns:us-east-1:123456789:impilo-events",
    }


class TestSNSEnvelopeUnwrap:
    """SQS consumer should unwrap SNS envelopes correctly."""

    @pytest.mark.asyncio
    async def test_sns_envelope_unwrapped(self) -> None:
        """When SQS message body has a 'Message' key, parse it as SNS envelope."""
        impilo_payload = {
            "type": "reading.weight",
            "id": 456,
            "patient": {"id": 123},
            "value": 185.5,
            "unit": "lbs",
            "createdAt": "2026-03-06T10:00:00Z",
        }
        sns_body = _wrap_in_sns_envelope(impilo_payload)
        sqs_msg = _make_sqs_message(sns_body)

        publisher = AsyncMock()
        sqs_client = AsyncMock()
        sqs_client.receive_message = AsyncMock(
            side_effect=[
                {"Messages": [sqs_msg]},
                asyncio.CancelledError(),
            ]
        )
        sqs_client.delete_message = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await sqs_consumer_loop(publisher, "https://sqs.test/queue", sqs_client=sqs_client)

        # Verify publish was called (event normalized from unwrapped payload)
        publisher.publish.assert_called_once()
        sqs_client.delete_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_payload_no_sns(self) -> None:
        """When SQS message body has no 'Message' key, treat as direct Impilo payload."""
        impilo_payload = {
            "type": "reading.weight",
            "id": 456,
            "patient": {"id": 123},
            "value": 185.5,
            "unit": "lbs",
            "createdAt": "2026-03-06T10:00:00Z",
        }
        sqs_msg = _make_sqs_message(impilo_payload)

        publisher = AsyncMock()
        sqs_client = AsyncMock()
        sqs_client.receive_message = AsyncMock(
            side_effect=[
                {"Messages": [sqs_msg]},
                asyncio.CancelledError(),
            ]
        )
        sqs_client.delete_message = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await sqs_consumer_loop(publisher, "https://sqs.test/queue", sqs_client=sqs_client)

        publisher.publish.assert_called_once()
        sqs_client.delete_message.assert_called_once()


class TestMalformedMessages:
    """Malformed messages should be logged and skipped, not crash the consumer."""

    @pytest.mark.asyncio
    async def test_malformed_message_skipped(self) -> None:
        """Invalid JSON body should not crash -- message is skipped (not deleted)."""
        sqs_msg = {
            "Body": "not valid json{{{",
            "ReceiptHandle": "rh-bad",
        }

        publisher = AsyncMock()
        sqs_client = AsyncMock()
        sqs_client.receive_message = AsyncMock(
            side_effect=[
                {"Messages": [sqs_msg]},
                asyncio.CancelledError(),
            ]
        )
        sqs_client.delete_message = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            await sqs_consumer_loop(publisher, "https://sqs.test/queue", sqs_client=sqs_client)

        # Malformed message should not be deleted (will return via visibility timeout)
        sqs_client.delete_message.assert_not_called()
        publisher.publish.assert_not_called()
