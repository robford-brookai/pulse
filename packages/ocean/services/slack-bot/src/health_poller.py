"""Connector health poller — alerts ops channel when connectors go silent."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import text

log = structlog.get_logger()

SILENCE_THRESHOLD_SECS = 300    # 5 minutes — exact, not configurable
REPEAT_INTERVAL_SECS = 1800     # 30 minutes — exact, not configurable


async def poll_connector_health(
    slack_client,
    ops_channel: str,
    session_maker,
) -> None:
    """Poll connector_health table and post to ops channel for silent connectors.

    Alerts when a connector's last_seen is older than SILENCE_THRESHOLD_SECS.
    Re-alerts only after REPEAT_INTERVAL_SECS has elapsed since last alert.
    Runs in a while-True loop with 60-second sleep; never crashes — logs exceptions.
    """
    while True:
        await asyncio.sleep(60)
        try:
            async with session_maker() as session:
                result = await session.execute(
                    text(
                        "SELECT connector_id, connector_name, last_seen, last_alerted_at "
                        "FROM connector_health "
                        "WHERE last_seen < now() - make_interval(secs => :threshold)"
                    ),
                    {"threshold": SILENCE_THRESHOLD_SECS},
                )
                silent_connectors = result.fetchall()

            now = datetime.now(tz=UTC)

            for row in silent_connectors:
                connector_id = row.connector_id
                connector_name = row.connector_name
                last_seen = row.last_seen
                last_alerted_at = row.last_alerted_at

                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=UTC)

                should_alert = last_alerted_at is None or (
                    now - (
                        last_alerted_at.replace(tzinfo=UTC)
                        if last_alerted_at.tzinfo is None
                        else last_alerted_at
                    )
                ).total_seconds() >= REPEAT_INTERVAL_SECS

                if not should_alert:
                    continue

                silent_minutes = int((now - last_seen).total_seconds() / 60)
                alert_text = (
                    f":warning: Connector *{connector_name}* has been silent for "
                    f"{silent_minutes} minutes. "
                    f"Last seen: {last_seen.isoformat()}"
                )

                await slack_client.chat_postMessage(
                    channel=ops_channel,
                    text=alert_text,
                )

                async with session_maker() as session:
                    async with session.begin():
                        await session.execute(
                            text(
                                "UPDATE connector_health "
                                "SET last_alerted_at = now() "
                                "WHERE connector_id = :connector_id"
                            ),
                            {"connector_id": connector_id},
                        )

                log.info(
                    "connector_health_alert_sent",
                    connector_id=connector_id,
                    connector_name=connector_name,
                    silent_minutes=silent_minutes,
                )

        except Exception:
            log.exception("health_poll_error")
