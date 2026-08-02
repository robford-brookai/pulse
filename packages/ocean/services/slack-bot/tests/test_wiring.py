"""Unit tests for slack-bot dependency wiring.

Verifies that main.py lifespan:
- Calls set_session_maker, set_publisher, set_hasura_secret on bolt_app
- Passes publisher kwarg to consumer.run_consumer
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# Pre-import the module (patching happens on the already-imported module attrs)
import src.main as main_mod


class TestSlackBotWiring:
    """Verify main.py lifespan wires bolt_app dependencies."""

    @pytest.mark.asyncio
    async def test_set_session_maker_called(self):
        """set_session_maker is called with a session_maker during lifespan."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch.object(main_mod, "SLACK_BOT_TOKEN", "xoxb-test"),
            patch.object(main_mod, "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test"),
            patch.object(main_mod, "REDPANDA_BROKERS", "localhost:9092"),
            patch.object(main_mod, "HASURA_URL", "http://localhost:8090"),
            patch.object(main_mod, "create_async_engine", return_value=mock_engine),
            patch.object(main_mod, "async_sessionmaker", return_value=MagicMock()),
            patch("src.main.asyncio.create_task"),
            patch("src.bolt_app.set_session_maker") as mock_set_sm,
            patch("src.bolt_app.set_publisher"),
            patch("src.bolt_app.set_hasura_secret"),
            patch("src.publisher.RedpandaPublisher"),
            patch("src.health_poller.poll_connector_health", new_callable=AsyncMock),
        ):
            app = MagicMock()
            app.add_api_route = MagicMock()

            async with main_mod.lifespan(app):
                pass

            mock_set_sm.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_publisher_called(self):
        """set_publisher is called with a RedpandaPublisher during lifespan."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch.object(main_mod, "SLACK_BOT_TOKEN", "xoxb-test"),
            patch.object(main_mod, "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test"),
            patch.object(main_mod, "REDPANDA_BROKERS", "localhost:9092"),
            patch.object(main_mod, "HASURA_URL", "http://localhost:8090"),
            patch.object(main_mod, "create_async_engine", return_value=mock_engine),
            patch.object(main_mod, "async_sessionmaker", return_value=MagicMock()),
            patch("src.main.asyncio.create_task"),
            patch("src.bolt_app.set_session_maker"),
            patch("src.bolt_app.set_publisher") as mock_set_pub,
            patch("src.bolt_app.set_hasura_secret"),
            patch("src.publisher.RedpandaPublisher"),
            patch("src.health_poller.poll_connector_health", new_callable=AsyncMock),
        ):
            app = MagicMock()
            app.add_api_route = MagicMock()

            async with main_mod.lifespan(app):
                pass

            mock_set_pub.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hasura_secret_called(self):
        """set_hasura_secret is called when HASURA_GRAPHQL_ADMIN_SECRET is set."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch.object(main_mod, "SLACK_BOT_TOKEN", "xoxb-test"),
            patch.object(main_mod, "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test"),
            patch.object(main_mod, "REDPANDA_BROKERS", "localhost:9092"),
            patch.object(main_mod, "HASURA_URL", "http://localhost:8090"),
            patch.object(main_mod, "create_async_engine", return_value=mock_engine),
            patch.object(main_mod, "async_sessionmaker", return_value=MagicMock()),
            patch("src.main.asyncio.create_task"),
            patch("src.bolt_app.set_session_maker"),
            patch("src.bolt_app.set_publisher"),
            patch("src.bolt_app.set_hasura_secret") as mock_set_hs,
            patch("src.publisher.RedpandaPublisher"),
            patch("src.health_poller.poll_connector_health", new_callable=AsyncMock),
            patch.dict(os.environ, {"HASURA_GRAPHQL_ADMIN_SECRET": "test-secret-123"}),
        ):
            app = MagicMock()
            app.add_api_route = MagicMock()

            async with main_mod.lifespan(app):
                pass

            mock_set_hs.assert_called_once_with("test-secret-123")

    @pytest.mark.asyncio
    async def test_run_consumer_receives_publisher(self):
        """run_consumer is called with publisher= keyword argument."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_publisher = MagicMock()

        import src.consumer as consumer_mod

        with (
            patch.object(main_mod, "SLACK_BOT_TOKEN", "xoxb-test"),
            patch.object(main_mod, "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test"),
            patch.object(main_mod, "REDPANDA_BROKERS", "localhost:9092"),
            patch.object(main_mod, "HASURA_URL", "http://localhost:8090"),
            patch.object(main_mod, "create_async_engine", return_value=mock_engine),
            patch.object(main_mod, "async_sessionmaker", return_value=MagicMock()),
            patch("src.main.asyncio.create_task"),
            patch("src.bolt_app.set_session_maker"),
            patch("src.bolt_app.set_publisher"),
            patch("src.bolt_app.set_hasura_secret"),
            patch("src.publisher.RedpandaPublisher", return_value=mock_publisher),
            patch("src.health_poller.poll_connector_health", new_callable=AsyncMock),
            patch.object(consumer_mod, "run_consumer", new_callable=AsyncMock) as mock_rc,
        ):
            app = MagicMock()
            app.add_api_route = MagicMock()

            async with main_mod.lifespan(app):
                pass

            mock_rc.assert_called_once()
            _, kwargs = mock_rc.call_args
            assert "publisher" in kwargs
            assert kwargs["publisher"] is not None
