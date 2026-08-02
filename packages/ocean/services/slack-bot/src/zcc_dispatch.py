"""Zoom Contact Center (ZCC) outbound call dispatch.

PHI boundary: patient_phone is PHI — must be retrieved from external PHI store
by patient_id hash, never stored in Ocean events.

MEDIUM confidence: ZCC Call Control endpoint inferred from
contact_center.call_control_make_call_executed webhook; verify endpoint
availability against account tier before production deploy.
"""

from __future__ import annotations

import time

import httpx
import structlog

log = structlog.get_logger()

# Module-level token cache — avoids a new OAuth round-trip on every dispatch.
_token_cache: dict = {"token": None, "expires_at": 0.0}


async def get_zcc_oauth_token(
    account_id: str,
    client_id: str,
    client_secret: str,
) -> str:
    """Obtain a Server-to-Server OAuth token for the ZCC API.

    Caches the token and refreshes only when within 100 seconds of expiry.
    """
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "account_credentials", "account_id": account_id},
            auth=(client_id, client_secret),
        )
        response.raise_for_status()
        data = response.json()

    token = data["access_token"]
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + 3500  # 1-hour tokens minus 100s buffer

    log.info("zcc_oauth_token_refreshed")
    return token


async def dispatch_zcc_outbound_call(
    zcc_token: str,
    agent_user_id: str,
    patient_phone: str,
    queue_id: str,
    task_id: str,
) -> dict:
    """Dispatch an outbound call through Zoom Contact Center.

    Returns the ZCC API response JSON. On HTTPStatusError (4xx): logs and
    re-raises so the caller can surface the failure to the Slack user.

    The task_id is passed in user_data so ZCC returns it on engagement completion
    (ZCC-02 correlation). patient_phone must come from PHI store — never stored
    in Ocean events.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                f"https://api.zoom.us/v2/contact_center/users/{agent_user_id}/commands",
                headers={"Authorization": f"Bearer {zcc_token}"},
                json={
                    "action": "make_call",
                    "params": {
                        "consumer_number": patient_phone,
                        "cc_queue_id": queue_id,
                        "user_data": {"task_id": task_id},
                    },
                },
            )
            response.raise_for_status()
            log.info("zcc_outbound_dispatched", task_id=task_id, queue_id=queue_id)
            return response.json()
        except httpx.HTTPStatusError as exc:
            log.error(
                "zcc_dispatch_http_error",
                status_code=exc.response.status_code,
                task_id=task_id,
            )
            raise
