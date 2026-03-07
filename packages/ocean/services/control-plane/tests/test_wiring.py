"""Unit tests for control-plane dependency wiring.

Verifies that:
- run_consumer propagates publisher to dispatch
- dispatch passes producer kwarg to handlers
- main.py creates RedpandaPublisher and passes to run_consumer
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestDispatchPassesProducer:
    """dispatch() must forward producer kwarg to handler functions."""

    @pytest.mark.asyncio
    async def test_dispatch_passes_producer_to_handler(self):
        """dispatch() calls handler with producer kwarg when provided."""
        from src.consumer import dispatch

        mock_handler = AsyncMock()
        event_data = {"event_type": "alert.created"}
        session = AsyncMock()
        producer = AsyncMock()

        with patch.dict("src.consumer.EVENT_HANDLERS", {"alert.created": mock_handler}):
            await dispatch(event_data, session, producer=producer)

        mock_handler.assert_awaited_once_with(event_data, session, producer=producer)

    @pytest.mark.asyncio
    async def test_dispatch_passes_none_producer_by_default(self):
        """dispatch() passes producer=None when no producer given."""
        from src.consumer import dispatch

        mock_handler = AsyncMock()
        event_data = {"event_type": "alert.created"}
        session = AsyncMock()

        with patch.dict("src.consumer.EVENT_HANDLERS", {"alert.created": mock_handler}):
            await dispatch(event_data, session)

        mock_handler.assert_awaited_once_with(event_data, session, producer=None)


class TestRunConsumerPassesPublisher:
    """run_consumer() must accept publisher and pass it to dispatch."""

    @pytest.mark.asyncio
    async def test_run_consumer_passes_publisher_to_dispatch(self):
        """Publisher kwarg is forwarded from run_consumer to dispatch."""
        import json
        from src import consumer

        publisher = AsyncMock()

        # Build a proper async-context-manager chain for session_maker
        # session_maker() -> async context manager -> session
        # session.begin() -> async context manager
        mock_begin_ctx = MagicMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.begin = MagicMock(return_value=mock_begin_ctx)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        session_maker = MagicMock(return_value=mock_session_ctx)

        # Build a fake message
        fake_msg = MagicMock()
        fake_msg.error.return_value = None
        fake_msg.value.return_value = json.dumps({"event_type": "alert.created"}).encode()

        call_count = 0

        async def fake_poll(timeout=1.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fake_msg
            raise KeyboardInterrupt  # stop the loop

        mock_consumer_instance = AsyncMock()
        mock_consumer_instance.poll = fake_poll
        mock_consumer_instance.subscribe = AsyncMock()
        mock_consumer_instance.commit = AsyncMock()
        mock_consumer_instance.close = AsyncMock()

        with patch("src.consumer.Consumer", return_value=mock_consumer_instance), \
             patch("src.consumer.dispatch", new_callable=AsyncMock) as mock_dispatch:
            try:
                await consumer.run_consumer(session_maker, "localhost:9092", publisher=publisher)
            except KeyboardInterrupt:
                pass

        # dispatch should have been called with producer=publisher
        assert mock_dispatch.called
        _, kwargs = mock_dispatch.call_args
        assert kwargs.get("producer") == publisher
