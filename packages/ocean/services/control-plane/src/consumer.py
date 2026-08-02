"""SQS consumer for control-plane.

Receives EventBridge-delivered events from control-plane's dedicated queue (rule
generated from ``CONSUMER_DOMAINS`` in ``ocean_broker.catalog``: alerts, ops,
tickets, logistics, tasks, interactions) and dispatches them to
``EVENT_HANDLERS``, one session transaction per message.

Receive → process → delete: a message is deleted only after its handler
transaction commits, so a failure is left to visibility-timeout redelivery and
the queue's redrive policy dead-letters a poison message. This preserves the
at-least-once, commit-after-success semantics the Kafka loop had. Blocking
boto3 calls run in a thread via ``asyncio.to_thread`` so the FastAPI event
loop — /health and the escalation poller — stays responsive.

Ordering verdict (task 3.6, DNA-743): **mixed, per handler** — see
``packages/ocean/docs/ordering-verdict-control-plane.md``. Eight of eleven
``EVENT_HANDLERS`` keys are order-tolerant; ``ticket.update.requested``
(event-time sequence guard, task 3.7), ``ticket.rma.requested`` and
``return.updated`` (silent drop when the precondition row is absent, task 3.8)
are order-dependent. ``ticket.created`` and ``ticket.updated`` are deliberately
absent (task 3.9): control-plane is their only publisher — every other service
sends the ``*.requested`` form — so routing them here consumed control-plane's
own output, and for ``ticket.created`` that echo minted a fresh ticket per
pass. Re-adding either key rebuilds the cycle;
``tests/test_ordering_verdicts.py`` guards against it.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.handlers.alerts import handle_alert_created
from src.handlers.deliveries import handle_delivery_notification
from src.handlers.heartbeats import handle_connector_heartbeat
from src.handlers.outcomes import (
    handle_alert_resolved,
    handle_call_completed,
    handle_call_missed,
    handle_task_completed,
)
from src.handlers.tickets import (
    handle_return_status_update,
    handle_rma_requested,
    handle_ticket_created,
    handle_ticket_updated,
)

log = structlog.get_logger()

SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME_SECONDS = 20
SQS_ERROR_BACKOFF_SECONDS = 5

EVENT_HANDLERS: dict = {
    "alert.created": handle_alert_created,
    "connector.heartbeat": handle_connector_heartbeat,
    "ticket.create.requested": handle_ticket_created,
    "ticket.update.requested": handle_ticket_updated,
    "ticket.rma.requested": handle_rma_requested,
    "return.updated": handle_return_status_update,
    "fulfillment.updated": handle_delivery_notification,
    "alert.resolved": handle_alert_resolved,
    "task.completed": handle_task_completed,
    "call.completed": handle_call_completed,
    "call.missed": handle_call_missed,
}


async def dispatch(event_data: dict, session: AsyncSession, producer=None) -> None:
    """Dispatch an event to the appropriate handler.

    Unknown event types are silently skipped (forward compatible).
    """
    event_type = event_data.get("event_type", "")
    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        log.debug("event_type_skipped", event_type=event_type)
        return
    await handler(event_data, session, producer=producer)


def _envelope_from_body(body: object) -> dict | None:
    """Extract the event envelope from a parsed SQS message body.

    An EventBridge rule delivers the envelope whole inside ``detail``. A body
    with no ``detail`` key is accepted as a bare envelope so local tooling can
    send straight to the queue.
    """
    if not isinstance(body, dict):
        return None
    detail = body.get("detail", body)
    return detail if isinstance(detail, dict) else None


async def run_consumer(
    session_maker: async_sessionmaker,
    queue_url: str,
    publisher=None,
    *,
    sqs_client: Any = None,
) -> None:
    """Run the control-plane consumer loop against its SQS queue.

    A message is deleted only after its handler transaction commits; a failed
    or malformed message is left for visibility-timeout redelivery, and the
    queue's redrive policy dead-letters a poison message.

    Args:
        session_maker: Async session maker; one transaction per message.
        queue_url: URL of the dedicated queue fed by control-plane's rule.
        publisher: Passed through to handlers as ``producer``.
        sqs_client: Optional pre-built SQS client (for testing). Defaults to a
            boto3 client resolving region from the environment.
    """
    if sqs_client is None:
        import boto3

        sqs_client = boto3.client("sqs")

    log.info("control_plane_consumer_started", queue_url=queue_url)

    while True:
        try:
            response = await asyncio.to_thread(
                sqs_client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=SQS_MAX_MESSAGES,
                WaitTimeSeconds=SQS_WAIT_TIME_SECONDS,
            )
        except asyncio.CancelledError:
            log.info("control_plane_consumer_closed")
            raise
        except Exception:
            log.exception("sqs_receive_failed", queue_url=queue_url)
            await asyncio.sleep(SQS_ERROR_BACKOFF_SECONDS)
            continue

        for msg in response.get("Messages", []):
            receipt_handle = msg.get("ReceiptHandle", "")

            try:
                body = json.loads(msg["Body"])
            except (json.JSONDecodeError, KeyError, TypeError):
                # Left undeleted on purpose: redelivery, then the DLQ redrive
                # policy retains it for inspection.
                log.warning("sqs_malformed_message", receipt_handle=receipt_handle)
                continue

            event_data = _envelope_from_body(body)
            if event_data is None:
                log.warning("sqs_body_not_an_envelope", receipt_handle=receipt_handle)
                continue

            try:
                async with session_maker() as session, session.begin():
                    await dispatch(event_data, session, producer=publisher)
            except asyncio.CancelledError:
                log.info("control_plane_consumer_closed")
                raise
            except Exception:
                log.exception(
                    "control_plane_dispatch_failed_no_delete",
                    receipt_handle=receipt_handle,
                    event_type=event_data.get("event_type", ""),
                )
                continue

            try:
                await asyncio.to_thread(
                    sqs_client.delete_message,
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt_handle,
                )
            except asyncio.CancelledError:
                log.info("control_plane_consumer_closed")
                raise
            except Exception:
                # A failed delete just redelivers; handlers absorb or log the
                # duplicate per their recorded verdicts.
                log.exception("sqs_delete_failed", receipt_handle=receipt_handle)
