"""SQS consumer for graph projection.

Receives EventBridge-delivered OCEAN events from the service's dedicated SQS
queue and upserts entity state into the operational graph. At-least-once,
delete-after-success: a message is deleted only after its DB transaction
commits, a failed message is left to visibility-timeout redelivery, and
repeated failure reaches the queue's redrive policy and DLQ.

Ordering verdict (design D3): MIXED, made order-tolerant by the event-time
sequence guards landed in tasks 3.1-3.4. Redelivery after a lost delete is
absorbed by the same guards and the handlers' dedup predicates.
"""

from __future__ import annotations

import asyncio
import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.handlers.alerts import handle_alert_claimed, handle_alert_created, handle_alert_resolved
from src.handlers.interactions import handle_call_connected, handle_call_started
from src.handlers.logistics import (
    handle_device_associated,
    handle_device_disassociated,
    handle_fulfillment_updated,
    handle_return_updated,
)
from src.handlers.ops import handle_connector_heartbeat, handle_scenario_completed
from src.handlers.outcomes import handle_call_completed, handle_call_missed, handle_outcome_recorded
from src.handlers.signals import (
    handle_signal_anomalous,
    handle_signal_missing,
    handle_signal_received,
)
from src.handlers.tasks import (
    handle_task_assigned,
    handle_task_claimed,
    handle_task_completed,
    handle_task_created,
)
from src.handlers.tickets import (
    handle_ticket_created,
    handle_ticket_resolved,
    handle_ticket_updated,
)

log = structlog.get_logger()

SQS_MAX_MESSAGES = 10
SQS_WAIT_TIME_S = 5
SQS_ERROR_BACKOFF_S = 5

EVENT_HANDLERS: dict = {
    "signal.received": handle_signal_received,
    "signal.missing": handle_signal_missing,
    "signal.anomalous": handle_signal_anomalous,
    "alert.created": handle_alert_created,
    "alert.claimed": handle_alert_claimed,
    "alert.resolved": handle_alert_resolved,
    "task.created": handle_task_created,
    "task.completed": handle_task_completed,
    "task.assigned": handle_task_assigned,
    "task.claimed": handle_task_claimed,
    "call.started": handle_call_started,
    "call.connected": handle_call_connected,
    "call.completed": handle_call_completed,
    "call.missed": handle_call_missed,
    "ticket.created": handle_ticket_created,
    "ticket.updated": handle_ticket_updated,
    "ticket.resolved": handle_ticket_resolved,
    "fulfillment.updated": handle_fulfillment_updated,
    "return.updated": handle_return_updated,
    "device.associated": handle_device_associated,
    "device.disassociated": handle_device_disassociated,
    "connector.heartbeat": handle_connector_heartbeat,
    "scenario.completed": handle_scenario_completed,
    "outcome.recorded": handle_outcome_recorded,
}


async def dispatch(event_data: dict, session: AsyncSession) -> None:
    """Dispatch an event to the appropriate handler.

    Unknown event types are silently skipped (forward compatible).
    """
    event_type = event_data.get("event_type", "")
    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        log.debug("event_type_skipped", event_type=event_type)
        return
    await handler(event_data, session)


def _parse_message(msg: dict) -> tuple[dict, str] | None:
    """Extract (event envelope, receipt handle) from an EventBridge→SQS message.

    The EventBridge event carries the envelope whole in ``detail``. A message
    that does not parse is returned as None and left undeleted, so the queue's
    redrive policy moves it to the DLQ.
    """
    receipt = msg["ReceiptHandle"]
    try:
        body = json.loads(msg["Body"])
        detail = body["detail"]
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("malformed_message", receipt_handle=receipt)
        return None
    if not isinstance(detail, dict):
        log.warning("malformed_message", receipt_handle=receipt)
        return None
    return detail, receipt


async def run_consumer(
    session_maker: async_sessionmaker,
    queue_url: str,
    *,
    sqs_client=None,
) -> None:
    """Receive → project into the graph → delete, one message at a time.

    A message is deleted only after its transaction commits; a handler failure
    leaves it for visibility-timeout redelivery. A failed delete is logged, not
    retried: the redelivered message is absorbed by the handlers' sequence
    guards and dedup predicates.
    """
    owns_client = sqs_client is None
    if owns_client:
        import aioboto3

        session = aioboto3.Session()
        sqs_client = await session.client("sqs").__aenter__()
    log.info("graph_consumer_started", queue_url=queue_url)

    try:
        while True:
            try:
                response = await sqs_client.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=SQS_MAX_MESSAGES,
                    WaitTimeSeconds=SQS_WAIT_TIME_S,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sqs_receive_failed", queue_url=queue_url)
                await asyncio.sleep(SQS_ERROR_BACKOFF_S)
                continue

            for msg in response.get("Messages", []):
                parsed = _parse_message(msg)
                if parsed is None:
                    continue
                event_data, receipt = parsed

                try:
                    async with session_maker() as session, session.begin():
                        await dispatch(event_data, session)
                except Exception:
                    log.exception(
                        "projection_failed_not_deleted",
                        event_type=event_data.get("event_type"),
                        receipt_handle=receipt,
                    )
                    continue

                try:
                    await sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
                except Exception:
                    log.exception("sqs_delete_failed", receipt_handle=receipt)
    finally:
        if owns_client:
            await sqs_client.__aexit__(None, None, None)
        log.info("graph_consumer_closed")
