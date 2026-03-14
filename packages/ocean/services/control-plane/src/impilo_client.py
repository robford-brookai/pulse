"""Async HTTP client for Impilo RMA creation.

POST /api/v3/return with retry logic for 5xx responses.
"""
from __future__ import annotations

import asyncio

import httpx
import structlog

log = structlog.get_logger()

RETRY_BACKOFFS = [0.5, 1.0, 2.0]


async def create_rma(
    api_url: str,
    api_key: str,
    patient_id: str,
    device_id: str,
    order_id: str,
    reason: str,
    ticket_id: str | None = None,
) -> dict:
    """Create an RMA via Impilo POST /api/v3/return.

    Validates required fields, retries up to 3 times on 5xx with exponential
    backoff (0.5s, 1.0s, 2.0s). Does NOT retry 4xx. Returns response JSON.
    """
    for field_name, value in [
        ("patient_id", patient_id),
        ("device_id", device_id),
        ("order_id", order_id),
    ]:
        if not value:
            raise ValueError(f"{field_name} must be a non-empty string")

    url = f"{api_url}/api/v3/return"
    headers = {"Authorization": f"Api-Key {api_key}"}
    body = {
        "patientId": patient_id,
        "deviceId": device_id,
        "orderId": order_id,
        "reason": reason,
    }

    last_error: httpx.HTTPStatusError | None = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(1 + len(RETRY_BACKOFFS)):
            response = await client.post(url, headers=headers, json=body)
            try:
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if response.status_code < 500:
                    raise
                last_error = exc
                if attempt < len(RETRY_BACKOFFS):
                    delay = RETRY_BACKOFFS[attempt]
                    log.warning(
                        "impilo_rma_retry",
                        attempt=attempt + 1,
                        status=response.status_code,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
