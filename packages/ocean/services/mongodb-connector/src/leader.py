"""Postgres advisory-lock based leader election for HA deployments.

Only one replica should actively watch MongoDB collections at a time.
``LeaderElector`` uses a **session-level** advisory lock
(``pg_try_advisory_lock``) on a **dedicated** (non-pooled) connection so
the lock lifetime is tied to the connection lifetime — if the process
crashes, Postgres detects the broken connection and releases the lock
automatically.

Usage::

    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(DATABASE_URL, pool_size=5)
    elector = LeaderElector(engine)

    if await elector.acquire():
        # We are the leader — start watching collections
        ...

    # On shutdown:
    await elector.release()
"""

from __future__ import annotations

import hashlib

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)

# Stable int64 lock ID derived from the service name.
# md5 → first 8 bytes → signed big-endian int64.
LOCK_ID: int = int.from_bytes(hashlib.md5(b"mongodb-connector").digest()[:8], "big", signed=True)

_ACQUIRE_SQL = text("SELECT pg_try_advisory_lock(:lock_id)")
_RELEASE_SQL = text("SELECT pg_advisory_unlock(:lock_id)")


class LeaderElector:
    """Acquire / release a Postgres session-level advisory lock.

    Parameters
    ----------
    engine:
        An ``AsyncEngine`` used to open a **dedicated** raw connection
        (bypassing the pool) for the lock.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._is_leader: bool = False
        self._conn = None  # dedicated raw connection

    # -- public API -----------------------------------------------------------

    @property
    def is_leader(self) -> bool:
        """Return *True* if this instance currently holds the lock."""
        return self._is_leader

    async def acquire(self) -> bool:
        """Try to acquire the advisory lock.

        Returns *True* if the lock was acquired (or already held).
        Returns *False* if another replica holds it (standby mode).
        On DB errors returns *False* and logs ``leader_check_failed``.
        """
        if self._is_leader:
            return True

        try:
            # Open a dedicated (non-pooled) connection so the lock
            # lifetime matches the connection lifetime.
            raw_conn = await self._engine.connect()
            # Detach from pool so close() truly closes the DBAPI conn.
            detached = await raw_conn.get_raw_connection()
            result = await raw_conn.execute(_ACQUIRE_SQL, {"lock_id": LOCK_ID})
            acquired = result.scalar()

            if acquired:
                self._is_leader = True
                self._conn = raw_conn
                logger.info("leader_acquired", lock_id=LOCK_ID)
                return True
            else:
                # We didn't get the lock — close the connection we opened.
                await raw_conn.close()
                logger.info("leader_standby", lock_id=LOCK_ID)
                return False

        except Exception as exc:
            logger.error("leader_check_failed", lock_id=LOCK_ID, error=str(exc))
            # Best-effort cleanup of the connection we may have opened.
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._is_leader = False
            return False

    async def release(self) -> None:
        """Release the advisory lock and close the dedicated connection.

        No-op if this instance is not the leader.
        """
        if not self._is_leader:
            return

        try:
            if self._conn is not None:
                await self._conn.execute(_RELEASE_SQL, {"lock_id": LOCK_ID})
                await self._conn.close()
        except Exception as exc:
            logger.warning("leader_release_error", lock_id=LOCK_ID, error=str(exc))
        finally:
            self._conn = None
            self._is_leader = False
            logger.info("leader_released", lock_id=LOCK_ID)
