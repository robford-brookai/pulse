"""Thread manager for Slack message lifecycle tracking.

Queues lifecycle events into organic batches (3-9s random delay) and posts
consolidated thread replies. Persists parent message_ts in slack_messages
for thread continuity across restarts.
"""
from __future__ import annotations

import asyncio
import random

import sqlalchemy as sa
import structlog

log = structlog.get_logger()


class ThreadManager:
    """Manages Slack thread tracking and batched lifecycle replies."""

    def __init__(self, slack_client, session_maker) -> None:
        self._slack = slack_client
        self._session_maker = session_maker
        self._batches: dict[str, list[dict]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    async def store_parent_message(self, task_id: str, channel: str, message_ts: str) -> None:
        """INSERT parent message into slack_messages (thread_ts = message_ts)."""
        async with self._session_maker() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO slack_messages (task_id, channel, message_ts, thread_ts) "
                    "VALUES (:task_id, :channel, :message_ts, :thread_ts)"
                ),
                {
                    "task_id": task_id,
                    "channel": channel,
                    "message_ts": message_ts,
                    "thread_ts": message_ts,
                },
            )
            await session.commit()
        log.info("parent_message_stored", task_id=task_id, channel=channel, ts=message_ts)

    async def get_thread_ts(self, task_id: str) -> str | None:
        """Look up thread_ts for a task_id from slack_messages."""
        async with self._session_maker() as session:
            result = await session.execute(
                sa.text("SELECT thread_ts FROM slack_messages WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            row = result.fetchone()
            return row.thread_ts if row else None

    async def queue_update(self, task_id: str, update: dict) -> None:
        """Append update to batch for task_id, start flush timer if needed."""
        if task_id not in self._batches:
            self._batches[task_id] = []
        self._batches[task_id].append(update)

        if task_id not in self._timers or self._timers[task_id].done():
            delay = random.uniform(3.0, 9.0)
            self._timers[task_id] = asyncio.create_task(self._flush_after(task_id, delay))

    async def _flush_after(self, task_id: str, delay: float) -> None:
        """Sleep then flush the batch for task_id."""
        await asyncio.sleep(delay)
        updates = self._batches.pop(task_id, [])
        if updates:
            await self._post_thread_reply(task_id, updates)

    async def _post_thread_reply(self, task_id: str, updates: list[dict]) -> None:
        """Post consolidated thread reply for batched updates."""
        thread_ts = await self.get_thread_ts(task_id)
        if not thread_ts:
            log.warning("thread_ts_not_found_skipping_reply", task_id=task_id)
            return

        # Look up channel from slack_messages
        async with self._session_maker() as session:
            result = await session.execute(
                sa.text("SELECT channel FROM slack_messages WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
            row = result.fetchone()
            if not row:
                log.warning("channel_not_found_skipping_reply", task_id=task_id)
                return
            channel = row.channel

        # Build consolidated blocks
        lines = []
        for u in updates:
            event_type = u.get("event_type", "update")
            lines.append(f"*{event_type}*")

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)},
            }
        ]

        await self._slack.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            blocks=blocks,
            text=f"{len(updates)} update(s)",
        )
        log.info("thread_reply_posted", task_id=task_id, update_count=len(updates))

    async def update_parent_status(self, task_id: str, new_status: str) -> None:
        """Update the parent message header with a status prefix."""
        async with self._session_maker() as session:
            result = await session.execute(
                sa.text(
                    "SELECT channel, message_ts FROM slack_messages WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            )
            row = result.fetchone()
            if not row:
                log.warning("parent_message_not_found", task_id=task_id)
                return

            channel = row.channel
            message_ts = row.message_ts

            # Update status in DB
            await session.execute(
                sa.text(
                    "UPDATE slack_messages SET status = :status, updated_at = now() "
                    "WHERE task_id = :task_id"
                ),
                {"status": new_status, "task_id": task_id},
            )
            await session.commit()

        # Update Slack message header
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"[{new_status.upper()}] Task {task_id}",
                    "emoji": True,
                },
            }
        ]
        await self._slack.chat_update(
            channel=channel,
            ts=message_ts,
            blocks=blocks,
            text=f"[{new_status.upper()}] Task {task_id}",
        )
        log.info("parent_status_updated", task_id=task_id, status=new_status)
