"""Integration: outreach approve → DB update → ZCC dispatch + ai.output.approved event.

Verifies AI-04 + AI-05 + ZCC-01 end-to-end with real Postgres:

1. Seed ai_drafts table with a 'pending' draft.
2. Call handle_outreach_approve with a mock Bolt body and real session_factory.
3. Assert:
   - DB row status changed to 'approved', actor_id set.
   - dispatch_zcc_outbound_call was called with correct task_id.
   - publish_ai_event was called with event_type='ai.output.approved' and draft_id.
"""
from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import sqlalchemy as sa

_ROOT = pathlib.Path(__file__).parents[2]

# Integration conftest adds slack-bot and graph-projection to sys.path.
# bolt_app imports from src.* which resolves to graph-projection (added first).
# We need slack-bot at position 0 for this file's src.bolt_app import.
# Use importlib to avoid the sys.modules["src"] conflict.
import importlib.util

pytestmark = pytest.mark.integration


def _load_slack_bot_module(module_path: str):
    """Load a slack-bot module by absolute path under a unique sys.modules key."""
    parts = module_path.replace(".", "/")
    file_path = _ROOT / "services" / "slack-bot" / "src" / f"{parts}.py"
    unique_name = f"_slack_bot_{module_path.replace('.', '_')}"
    if unique_name in sys.modules:
        return sys.modules[unique_name]
    spec = importlib.util.spec_from_file_location(unique_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_bolt_body(draft_id: str, actor_id: str = "U_CARE_COORD") -> dict:
    return {
        "actions": [{"action_id": "outreach_approve", "value": draft_id}],
        "user": {"id": actor_id},
        "container": {"channel_id": "C_INTEG", "message_ts": "999.111"},
    }


@pytest.fixture
async def seeded_draft(session_factory):
    """Insert a pending ai_drafts row and return its draft_id."""
    draft_id = "draft-integ-001"
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                sa.text(
                    "INSERT INTO ai_drafts (draft_id, task_id, patient_id, alert_id, status) "
                    "VALUES (:draft_id, 'task-integ-001', 'pt-integ-001', 'alert-integ-001', 'pending') "
                    "ON CONFLICT (draft_id) DO UPDATE SET status='pending', actor_id=NULL"
                ),
                {"draft_id": draft_id},
            )
    return draft_id


@pytest.mark.asyncio
async def test_approve_updates_db_status_to_approved(session_factory, seeded_draft):
    """After handle_outreach_approve, ai_drafts.status = 'approved' and actor_id is set."""
    bolt_app_mod = _load_slack_bot_module("bolt_app")

    bolt_app_mod.set_session_maker(session_factory)
    bolt_app_mod.set_publisher(AsyncMock())

    mock_client = AsyncMock()
    mock_client.chat_postEphemeral = AsyncMock()
    mock_client.chat_update = AsyncMock()

    with patch.object(
        sys.modules.get("_slack_bot_bolt_app", bolt_app_mod),
        "dispatch_zcc_outbound_call",
        new=AsyncMock(return_value={"zcc_engagement_id": "eng-stub"}),
    ):
        with patch.object(
            sys.modules.get("_slack_bot_bolt_app", bolt_app_mod),
            "publish_ai_event",
            new=AsyncMock(),
        ):
            with patch.dict("os.environ", {"PHI_STORE_URL": ""}):
                await bolt_app_mod.handle_outreach_approve(
                    ack=AsyncMock(),
                    body=_make_bolt_body(seeded_draft, actor_id="U_COORD"),
                    client=mock_client,
                )

    # Verify DB state
    async with session_factory() as session:
        result = await session.execute(
            sa.text("SELECT status, actor_id FROM ai_drafts WHERE draft_id = :id"),
            {"id": seeded_draft},
        )
        row = result.fetchone()

    assert row is not None
    assert row.status == "approved", f"Expected 'approved', got '{row.status}'"
    assert row.actor_id == "U_COORD", f"Expected actor_id='U_COORD', got '{row.actor_id}'"


@pytest.mark.asyncio
async def test_approve_calls_dispatch_with_task_id(session_factory, seeded_draft):
    """dispatch_zcc_outbound_call is called with the task_id from the seeded draft."""
    bolt_app_mod = _load_slack_bot_module("bolt_app")
    bolt_app_mod.set_session_maker(session_factory)
    bolt_app_mod.set_publisher(AsyncMock())

    dispatch_mock = AsyncMock(return_value={"zcc_engagement_id": "eng-stub"})
    captured_publish: list[dict] = []

    async def capture_publish(publisher, event_type, task_id, patient_id, payload):
        captured_publish.append({"event_type": event_type, "task_id": task_id, "payload": payload})

    # Reset draft to pending
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                sa.text("UPDATE ai_drafts SET status='pending', actor_id=NULL WHERE draft_id=:id"),
                {"id": seeded_draft},
            )

    with patch.object(bolt_app_mod, "dispatch_zcc_outbound_call", new=dispatch_mock):
        with patch.object(bolt_app_mod, "publish_ai_event", new=capture_publish):
            with patch.dict("os.environ", {"PHI_STORE_URL": ""}):
                await bolt_app_mod.handle_outreach_approve(
                    ack=AsyncMock(),
                    body=_make_bolt_body(seeded_draft),
                    client=AsyncMock(),
                )

    dispatch_mock.assert_awaited_once()
    _, kwargs = dispatch_mock.call_args
    assert kwargs.get("task_id") == "task-integ-001", (
        f"ZCC-01: dispatch task_id expected 'task-integ-001', got '{kwargs.get('task_id')}'"
    )

    approved_events = [e for e in captured_publish if e["event_type"] == "ai.output.approved"]
    assert len(approved_events) >= 1, "ai.output.approved event not published"
    assert approved_events[0]["payload"]["draft_id"] == seeded_draft
