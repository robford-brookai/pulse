"""SQS consumer for outreach approval events on the ``ai-ops`` domain.

Ordering verdict (design D3): **order-tolerant**. The consumer reads one domain and issues one
independent call-simulation dispatch per approval event; no dispatch reads state written by
another, so delivery order cannot affect the final state. No sequence guard is required.

The receive → process → delete loop preserves the Kafka consumer's commit-after-dispatch,
at-least-once semantics: a message is deleted only after its simulation is dispatched, and a
failed dispatch leaves the message for redelivery via visibility-timeout expiry. Undecodable
and filtered messages are deleted, matching the old commit-and-skip behaviour.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
from typing import Any

import boto3
import structlog
from ocean_broker import EventBridgePublisher

from src.call_sim import simulate_call

log = structlog.get_logger()

#: The one live OCEAN domain this service consumes — the former ``ocean.ai-ops`` topic.
DOMAIN = "ai-ops"
FILTER_EVENT_TYPE = "ai.output.approved"

MAX_MESSAGES = 10
WAIT_TIME_SECONDS = 20
RECEIVE_ERROR_BACKOFF_SECONDS = 5


class AIOConsumer:
    """Async wrapper around an SQS receive/process/delete loop.

    Long-polls the service's dedicated queue for ``ai-ops`` events and dispatches call
    simulations as non-blocking background tasks. The blocking boto3 calls run in the default
    executor, mirroring the shape the confluent-kafka poll loop had.
    """

    def __init__(
        self,
        queue_url: str,
        publisher: EventBridgePublisher,
        sqs_client: Any | None = None,
    ) -> None:
        """Wire the consumer to its queue.

        Args:
            queue_url: URL of the dedicated SQS queue fed by this consumer's EventBridge rule.
            publisher: Shared publisher handed to each dispatched simulation.
            sqs_client: Optional pre-built SQS client (for testing). Defaults to a boto3 client
                for ``AWS_REGION``, falling back to ``us-east-1``.
        """
        self._queue_url = queue_url
        self._publisher = publisher
        self._client = sqs_client or boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self._running = False

    async def start(self) -> None:
        """Begin polling in a loop until :meth:`stop` is called."""
        self._running = True
        log.info("consumer_started", queue_url=self._queue_url, domain=DOMAIN)

        while self._running:
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Receive one batch and process it, deleting each message that is consumed."""
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None,
                functools.partial(
                    self._client.receive_message,
                    QueueUrl=self._queue_url,
                    MaxNumberOfMessages=MAX_MESSAGES,
                    WaitTimeSeconds=WAIT_TIME_SECONDS,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("consumer_receive_error", error=str(exc))
            await asyncio.sleep(RECEIVE_ERROR_BACKOFF_SECONDS)
            return

        for message in response.get("Messages", []):
            if self._process(message):
                await self._delete(message)

    def _process(self, message: dict[str, Any]) -> bool:
        """Handle one message; True means it is consumed and may be deleted.

        The envelope crosses the bus whole inside EventBridge ``detail``; everything else in
        the body is bus framing. A body that does not carry a dict there is poison — deleted,
        like the Kafka consumer committed past undecodable payloads — because redelivery
        cannot fix it.
        """
        try:
            body = json.loads(message["Body"])
            event_data = body["detail"]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            log.warning("consumer_decode_error", error=str(exc))
            return True

        if not isinstance(event_data, dict):
            log.warning("consumer_decode_error", error="detail is not an object")
            return True

        if event_data.get("event_type") != FILTER_EVENT_TYPE:
            return True

        log.info(
            "approval_received",
            event_id=event_data.get("event_id"),
            correlation_id=event_data.get("correlation_id"),
        )

        try:
            # Dispatch call simulation as non-blocking task
            asyncio.create_task(simulate_call(event_data, self._publisher))
        except Exception as exc:
            log.error("consumer_dispatch_error", error=str(exc))
            return False

        return True

    async def _delete(self, message: dict[str, Any]) -> None:
        """Delete a consumed message; a failed delete only means one redundant redelivery."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                functools.partial(
                    self._client.delete_message,
                    QueueUrl=self._queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                ),
            )
        except Exception as exc:
            log.error("consumer_delete_error", error=str(exc))

    def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False
        log.info("consumer_stopped")
