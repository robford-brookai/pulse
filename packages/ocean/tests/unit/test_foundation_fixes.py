"""Tests for Phase 28 foundation fixes: EventType literals, Hasura tables, retry logic."""

from __future__ import annotations

import ast
import pathlib
import typing

from ocean_events.types import EventType

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_event_type_literals_complete():
    """EventType Literal includes ai.output.confirmed, ai.output.overridden, connector.heartbeat."""
    args = typing.get_args(EventType)
    assert "ai.output.confirmed" in args
    assert "ai.output.overridden" in args
    assert "connector.heartbeat" in args


def test_hasura_all_tables_includes_ops_tables():
    """apply_metadata.py ALL_TABLES includes connector_health and simulations."""
    src = (ROOT / "infra" / "hasura" / "apply_metadata.py").read_text()
    start = src.index("ALL_TABLES = [")
    end = src.index("]", start) + 1
    tables = ast.literal_eval(src[start + len("ALL_TABLES = ") : end])
    assert "connector_health" in tables
    assert "simulations" in tables


def test_update_parent_status_has_retry():
    """update_parent_status in thread_manager.py retries once after 2s."""
    src = (ROOT / "services" / "slack-bot" / "src" / "thread_manager.py").read_text()
    # Extract the method body
    method_start = src.index("async def update_parent_status")
    # Find the next method or end of class
    next_method = src.find("\n    async def ", method_start + 1)
    end = len(src) if next_method == -1 else next_method
    method_body = src[method_start:end]
    assert "asyncio.sleep(2)" in method_body, "update_parent_status must retry after 2s"
    assert "parent_message_not_found_retrying" in method_body
    assert "parent_message_not_found_giving_up" in method_body
