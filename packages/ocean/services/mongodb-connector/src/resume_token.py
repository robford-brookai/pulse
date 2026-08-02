"""Async Postgres store for CDC resume tokens.

The CollectionWatcher calls ``save_token`` after every published event so
that on restart it can ``get_token`` and hand the resume token back to
Motor's ``watch(resume_after=...)``.  The store uses an UPSERT pattern —
callers never need to check whether a row exists first.
"""
from __future__ import annotations

import json

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_UPSERT_SQL = text(
    "INSERT INTO cdc_resume_tokens (collection_name, resume_token, updated_at) "
    "VALUES (:collection, :token, now()) "
    "ON CONFLICT (collection_name) DO UPDATE "
    "SET resume_token = EXCLUDED.resume_token, updated_at = now()"
)

_SELECT_SQL = text(
    "SELECT resume_token FROM cdc_resume_tokens "
    "WHERE collection_name = :collection"
)

_DELETE_SQL = text(
    "DELETE FROM cdc_resume_tokens WHERE collection_name = :collection"
)


class ResumeTokenStore:
    """Persist and retrieve MongoDB change-stream resume tokens in Postgres."""

    async def get_token(
        self, session: AsyncSession, collection: str
    ) -> dict | None:
        """Return the stored resume token dict, or *None* if absent."""
        result = await session.execute(
            _SELECT_SQL, {"collection": collection}
        )
        row = result.fetchone()
        if row is None:
            logger.debug("resume_token_not_found", collection=collection)
            return None
        token = row[0]
        # SQLAlchemy returns Python dict for JSONB; fall back to json.loads
        # if the driver returns a raw string.
        if isinstance(token, str):
            token = json.loads(token)
        logger.debug("resume_token_loaded", collection=collection)
        return token

    async def save_token(
        self, session: AsyncSession, collection: str, token: dict
    ) -> None:
        """UPSERT the resume token for *collection*."""
        await session.execute(
            _UPSERT_SQL,
            {"collection": collection, "token": json.dumps(token)},
        )
        await session.commit()
        logger.info("resume_token_saved", collection=collection)

    async def delete_token(
        self, session: AsyncSession, collection: str
    ) -> None:
        """Remove the resume token for *collection* (e.g. on full resync)."""
        await session.execute(_DELETE_SQL, {"collection": collection})
        await session.commit()
        logger.debug("resume_token_deleted", collection=collection)
