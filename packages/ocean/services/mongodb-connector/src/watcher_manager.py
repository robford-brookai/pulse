"""WatcherManager — concurrent asyncio orchestration of per-collection CDC watchers.

Spawns one ``CollectionWatcher`` per registered MongoDB collection, running
each as an independent asyncio task.  A single watcher failure is logged but
does not bring down the others.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from motor.motor_asyncio import AsyncIOMotorDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.publisher import EventPublisher
from src.resume_token import ResumeTokenStore
from src.transformer import BaseTransformer
from src.watcher import CollectionWatcher

logger = structlog.get_logger(__name__)


class WatcherManager:
    """Manage a fleet of ``CollectionWatcher`` tasks — one per collection."""

    def __init__(
        self,
        *,
        db: AsyncIOMotorDatabase,
        publisher: EventPublisher,
        token_store: ResumeTokenStore,
        db_session_factory: async_sessionmaker,
        transformer_registry: dict[str, BaseTransformer],
        collections: list[str] | None = None,
        topic: str = "ocean.patient-state",
    ) -> None:
        # Default to all registered collections when none specified.
        if collections is None:
            collections = list(transformer_registry.keys())

        # Validate every requested collection has a transformer.
        unknown = set(collections) - set(transformer_registry.keys())
        if unknown:
            raise ValueError(
                f"Unknown collection(s) with no registered transformer: {sorted(unknown)}"
            )

        self._db = db
        self._publisher = publisher
        self._token_store = token_store
        self._session_factory = db_session_factory
        self._registry = transformer_registry
        self._collections = collections
        self._topic = topic
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Create and launch one watcher task per collection."""
        for name in self._collections:
            watcher = CollectionWatcher(
                collection=self._db[name],
                transformer=self._registry[name],
                publisher=self._publisher,
                token_store=self._token_store,
                db_session_factory=self._session_factory,
                topic=self._topic,
                collection_name=name,
            )
            task = asyncio.create_task(
                watcher.watch(shutdown_event), name=f"watcher-{name}"
            )
            task.add_done_callback(self._on_task_done)
            self._tasks[name] = task

        logger.info(
            "watcher_manager_started",
            collection_count=len(self._tasks),
            collections=self._collections,
        )

    async def stop(self) -> None:
        """Cancel every watcher task and wait for them to finish."""
        for task in self._tasks.values():
            task.cancel()

        results = await asyncio.gather(
            *self._tasks.values(), return_exceptions=True
        )

        # Log any non-cancellation exceptions that surfaced during shutdown.
        for name, result in zip(self._tasks.keys(), results):
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.error(
                    "watcher_task_failed",
                    collection=name,
                    error=str(result),
                )

        self._tasks.clear()
        logger.info("watcher_manager_stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """Log unexpected task exits without crashing the manager."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # Derive collection name from task name ("watcher-<collection>").
            collection = (task.get_name() or "").removeprefix("watcher-")
            logger.error(
                "watcher_task_failed",
                collection=collection,
                error=str(exc),
            )
