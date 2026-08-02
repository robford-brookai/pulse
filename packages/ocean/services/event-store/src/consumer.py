"""SQS consumer for the OCEAN event store.

Polls the event-store queue fed by its EventBridge rule and writes every
event to the Postgres event store. The rule matches all eleven live domains
(``CONSUMER_DOMAINS["event-store"]`` is ``LIVE_DOMAINS``, task 5.8) — the
Kafka-era subscription claimed "all Ocean topics" but listed only nine,
silently omitting ``tickets`` and ``patient-state``. A message is deleted only AFTER the DB
write succeeds; a failed message is left to visibility-timeout expiry and
redelivered, then dead-lettered by the queue's redrive policy. This keeps
the at-least-once, commit-after-success semantics the Kafka loop had.

Ordering verdict: order-tolerant. The store is append-only with
``ON CONFLICT (event_id) DO NOTHING`` (writer.py), so delivery order cannot
affect the final state.

Each SQS message body is an EventBridge event: the envelope travels whole
in ``detail`` and the domain is ``detail-type`` (design D1).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

log = structlog.get_logger()

SQS_POLL_RETRY_INTERVAL = 5
SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME = 20


async def run_consumer(writer: Any, queue_url: str, *, sqs_client: Any = None) -> None:
    """Run the event store consumer loop.

    Args:
        writer: Module with async write_event(bytes, topic) function.
        queue_url: SQS queue URL for the event-store consumer.
        sqs_client: Optional pre-built SQS client (for testing). If None,
            creates one via aioboto3.

    CancelledError propagates for clean shutdown.
    """
    owns_client = sqs_client is None
    if owns_client:
        import aioboto3

        session = aioboto3.Session()
        sqs_client = await session.client("sqs").__aenter__()
    log.info("consumer_started", queue_url=queue_url)

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
                await asyncio.sleep(SQS_POLL_RETRY_INTERVAL)
                continue

            for msg in response.get("Messages", []):
                try:
                    body = json.loads(msg["Body"])
                    envelope = body["detail"]
                    detail_type = body["detail-type"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Left undeleted on purpose: redelivery, then the DLQ
                    # redrive policy retains it for inspection.
                    log.warning("sqs_malformed_message", receipt_handle=msg.get("ReceiptHandle"))
                    continue

                try:
                    await writer.write_event(json.dumps(envelope).encode(), topic=detail_type)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception(
                        "write_failed_no_delete",
                        receipt_handle=msg["ReceiptHandle"],
                        detail_type=detail_type,
                    )
                    # Do NOT delete — visibility timeout redelivers the message
                    continue

                # Delete only after successful DB write. A failed delete just
                # redelivers, and the idempotent write absorbs the duplicate.
                try:
                    await sqs_client.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("sqs_delete_failed", receipt_handle=msg["ReceiptHandle"])
    finally:
        if owns_client:
            await sqs_client.__aexit__(None, None, None)
        log.info("consumer_closed")
