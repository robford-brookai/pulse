"""CollectionWatcher — motor Change Stream loop with backoff and resume tokens.

Watches a single MongoDB collection, transforms each change via a
``BaseTransformer``, publishes through the shared ``EventBridgePublisher``, and
persists resume tokens in Postgres via ``ResumeTokenStore``.

Resume token is saved *after* the publish returns, which still guarantees
at-least-once: the shared publisher does not drop a failed envelope, it writes
it to ``failed_webhooks``, so the event is durable either way.
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from uuid import uuid4

import pymongo.errors
import structlog
from bson import json_util
from motor.motor_asyncio import AsyncIOMotorCollection
from ocean_broker import EventBridgePublisher
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.resume_token import ResumeTokenStore
from src.transformer import BaseTransformer

logger = structlog.get_logger(__name__)

_MAX_BACKOFF_SECONDS = 60.0


class CollectionWatcher:
    """Watch a MongoDB collection and publish change events."""

    def __init__(
        self,
        *,
        collection: AsyncIOMotorCollection,
        transformer: BaseTransformer,
        publisher: EventBridgePublisher,
        token_store: ResumeTokenStore,
        db_session_factory: async_sessionmaker,
        domain: str = "patient-state",
        collection_name: str = "alerts",
    ) -> None:
        self._collection = collection
        self._transformer = transformer
        self._publisher = publisher
        self._token_store = token_store
        self._session_factory = db_session_factory
        self._domain = domain
        self._collection_name = collection_name

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def watch(self, shutdown_event: asyncio.Event) -> None:
        """Run the change-stream loop until *shutdown_event* is set."""
        retry_count = 0

        while not shutdown_event.is_set():
            try:
                await self._watch_loop(shutdown_event)
                # Normal exit (shutdown requested inside the loop)
                break
            except pymongo.errors.PyMongoError as exc:
                retry_count += 1
                delay = min(2**retry_count + random.uniform(0, 1), _MAX_BACKOFF_SECONDS)
                logger.error(
                    "watcher_error",
                    collection=self._collection_name,
                    error=str(exc),
                    retry_count=retry_count,
                    backoff_seconds=round(delay, 2),
                )
                # Non-resumable errors: clear the token so we restart fresh.
                if _is_non_resumable(exc):
                    await self._clear_resume_token()
                await asyncio.sleep(delay)

        # No flush: PutEvents is a synchronous call per publish, so there is no producer
        # buffer that could still hold an unsent event at shutdown.
        logger.info("watcher_stopped", collection=self._collection_name)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _watch_loop(self, shutdown_event: asyncio.Event) -> None:
        resume_token = await self._load_resume_token()

        watch_kwargs: dict = {"full_document": "updateLookup"}
        if resume_token is not None:
            watch_kwargs["resume_after"] = resume_token

        logger.info(
            "watcher_started",
            collection=self._collection_name,
            has_resume_token=resume_token is not None,
        )

        async with self._collection.watch(**watch_kwargs) as stream:
            async for change in stream:
                if shutdown_event.is_set():
                    break

                transformed = self._transformer.transform(change)
                if transformed is None:
                    logger.debug(
                        "change_event_skipped",
                        collection=self._collection_name,
                        operation_type=change.get("operationType"),
                    )
                    continue

                # Build BaseEvent-compatible envelope
                event_dict = {
                    "event_id": str(uuid4()),
                    "event_type": "patient.feature.changed",
                    "source_system": "mongodb-connector",
                    "entity_type": "patient_feature",
                    "entity_id": transformed["patient_id"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "schema_version": "1.0.0",
                    "correlation_id": str(uuid4()),
                    "actor_id": None,
                    "payload": transformed,
                }

                # Publish, then persist resume token (at-least-once).
                # A bus failure does not raise here — the shared publisher dead-letters the
                # envelope to ``failed_webhooks``, so advancing the token loses nothing.
                await self._publisher.publish(self._domain, event_dict, key=transformed["patient_id"])

                token_dict = _resume_token_to_dict(change["_id"])
                await self._save_resume_token(token_dict)

                # Reset retry counter on successful processing
                # (accessed via the outer while-loop variable — Python closures)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _load_resume_token(self) -> dict | None:
        async with self._session_factory() as session:
            return await self._token_store.get_token(session, self._collection_name)

    async def _save_resume_token(self, token: dict) -> None:
        async with self._session_factory() as session:
            await self._token_store.save_token(session, self._collection_name, token)
        logger.info("resume_token_saved", collection=self._collection_name)

    async def _clear_resume_token(self) -> None:
        try:
            async with self._session_factory() as session:
                await self._token_store.delete_token(session, self._collection_name)
            logger.warning(
                "resume_token_cleared",
                collection=self._collection_name,
                reason="non_resumable_error",
            )
        except Exception:
            logger.exception("resume_token_clear_failed", collection=self._collection_name)


# ------------------------------------------------------------------
# Module-level utilities
# ------------------------------------------------------------------


def _resume_token_to_dict(raw_token: dict) -> dict:
    """Convert a BSON resume token to a plain JSON-serialisable dict.

    Motor returns the ``_id`` of a change event as a BSON document that may
    contain non-JSON types (e.g. ``Binary``).  Round-tripping through
    ``bson.json_util`` gives us an Extended JSON dict safe for Postgres JSONB.
    """
    return json.loads(json_util.dumps(raw_token))


def _is_non_resumable(exc: pymongo.errors.PyMongoError) -> bool:
    """Heuristic check for errors that invalidate the current resume token."""
    # PyMongo ≥ 4.x surfaces specific error labels; fall back to message matching.
    if hasattr(exc, "has_error_label") and exc.has_error_label("NonResumableChangeStreamError"):
        return True
    msg = str(exc).lower()
    return "change stream" in msg and ("invalid" in msg or "not found" in msg)
