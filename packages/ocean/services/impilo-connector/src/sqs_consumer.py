"""SQS consumer background task for Impilo SNS fan-out.

Polls an SQS queue, unwraps SNS envelopes, normalizes Impilo payloads,
and publishes to Redpanda. Feature-flagged by SQS_QUEUE_URL env var.
"""
from __future__ import annotations

import asyncio
import json

import structlog

from src.normalizer import normalize_impilo_payload

log = structlog.get_logger()

SQS_POLL_INTERVAL = 5
SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME = 20


async def sqs_consumer_loop(
    publisher,
    queue_url: str,
    *,
    sqs_client=None,
) -> None:
    """Infinite loop that polls SQS, unwraps SNS envelopes, and publishes to Redpanda.

    Args:
        publisher: RedpandaPublisher instance.
        queue_url: SQS queue URL to poll.
        sqs_client: Optional pre-built SQS client (for testing). If None, creates
            one via aioboto3.

    CancelledError propagates for clean shutdown (same pattern as heartbeat).
    """
    owns_client = sqs_client is None
    if owns_client:
        import aioboto3

        session = aioboto3.Session()
        sqs_client = await session.client("sqs").__aenter__()

    try:
        while True:
            try:
                response = await sqs_client.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=SQS_MAX_MESSAGES,
                    WaitTimeSeconds=SQS_WAIT_TIME,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sqs_receive_failed", queue_url=queue_url)
                await asyncio.sleep(SQS_POLL_INTERVAL)
                continue

            messages = response.get("Messages", [])
            for msg in messages:
                try:
                    body = json.loads(msg["Body"])
                except (json.JSONDecodeError, KeyError):
                    log.warning("sqs_malformed_message", receipt_handle=msg.get("ReceiptHandle"))
                    continue

                # Unwrap SNS envelope if present
                if "Message" in body and isinstance(body.get("Message"), str):
                    try:
                        payload = json.loads(body["Message"])
                    except json.JSONDecodeError:
                        log.warning("sqs_sns_unwrap_failed", receipt_handle=msg["ReceiptHandle"])
                        continue
                else:
                    payload = body

                try:
                    event, topic = normalize_impilo_payload(payload)
                    await publisher.publish(
                        topic=topic,
                        key=str(event.event_id),
                        value=json.dumps(event.model_dump(mode="json")).encode(),
                    )
                except Exception:
                    log.exception(
                        "sqs_normalize_publish_failed",
                        receipt_handle=msg["ReceiptHandle"],
                    )
                    continue

                # Delete only after successful publish
                try:
                    await sqs_client.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                except Exception:
                    log.exception("sqs_delete_failed", receipt_handle=msg["ReceiptHandle"])

    finally:
        if owns_client:
            await sqs_client.__aexit__(None, None, None)
