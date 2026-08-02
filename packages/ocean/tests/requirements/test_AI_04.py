"""AI-04: Approve button required before ZCC dispatch.

Requirement: No outbound ZCC call is dispatched unless a care coordinator
explicitly presses the "Approve & Dispatch" button. The handler acks first
(Slack 3s timeout), atomically marks the draft approved in the DB, and only
then dispatches to ZCC. If the draft is already processed, dispatch is skipped.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils import setup_service

setup_service("slack-bot")

import src.bolt_app as _bolt_app_mod  # noqa: E402
from src.bolt_app import handle_outreach_approve, set_publisher, set_session_maker  # noqa: E402


def _body(draft_id: str = "draft-001") -> dict:
    return {
        "actions": [{"action_id": "outreach_approve", "value": draft_id}],
        "user": {"id": "U_ACTOR"},
        "container": {"channel_id": "C_CHAN", "message_ts": "111.222"},
    }


def _make_row(draft_id: str = "draft-001", task_id: str = "task-xyz", patient_id: str = "pt-hash"):
    row = MagicMock()
    row.draft_id = draft_id
    row.task_id = task_id
    row.patient_id = patient_id
    row.alert_id = "alert-abc"
    return row


@pytest.mark.asyncio
async def test_approve_acks_before_db_and_dispatch():
    """ack() is the first call — before any DB write or ZCC dispatch."""
    call_log: list[str] = []

    async def tracking_ack():
        call_log.append("ack")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        side_effect=lambda *a, **kw: (call_log.append("db"), MagicMock(fetchone=MagicMock(return_value=_make_row())))[1]
    )
    mock_session.commit = AsyncMock()

    set_session_maker(MagicMock(return_value=mock_session))
    set_publisher(AsyncMock())

    mock_client = AsyncMock()
    mock_client.chat_postEphemeral = AsyncMock(side_effect=lambda **kw: call_log.append("ephemeral"))
    mock_client.chat_update = AsyncMock(side_effect=lambda **kw: call_log.append("chat_update"))

    with patch.object(_bolt_app_mod, "dispatch_zcc_outbound_call", new=AsyncMock(
        side_effect=lambda **kw: (call_log.append("dispatch"), {"stubbed": True})[1]
    )):
        with patch.object(_bolt_app_mod, "publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": ""}):
                await handle_outreach_approve(ack=tracking_ack, body=_body(), client=mock_client)

    assert call_log[0] == "ack", f"ack() was not first; order: {call_log}"
    assert "db" in call_log
    assert "dispatch" in call_log
    db_idx = call_log.index("db")
    dispatch_idx = call_log.index("dispatch")
    assert db_idx < dispatch_idx, "DB write must precede ZCC dispatch"


@pytest.mark.asyncio
async def test_dispatch_not_called_when_draft_already_processed():
    """ZCC dispatch is skipped if the draft was already approved/rejected."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    # DB returns None — draft already processed
    mock_session.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=None))
    )
    mock_session.commit = AsyncMock()

    set_session_maker(MagicMock(return_value=mock_session))
    set_publisher(AsyncMock())

    mock_client = AsyncMock()
    mock_client.chat_postEphemeral = AsyncMock()

    dispatch_mock = AsyncMock(return_value={"stubbed": True})

    with patch.object(_bolt_app_mod, "dispatch_zcc_outbound_call", new=dispatch_mock):
        with patch.object(_bolt_app_mod, "publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": ""}):
                await handle_outreach_approve(ack=AsyncMock(), body=_body(), client=mock_client)

    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_called_when_draft_approved():
    """ZCC dispatch IS called when a draft is successfully approved."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=_make_row()))
    )
    mock_session.commit = AsyncMock()

    set_session_maker(MagicMock(return_value=mock_session))
    set_publisher(AsyncMock())

    mock_client = AsyncMock()
    mock_client.chat_postEphemeral = AsyncMock()
    mock_client.chat_update = AsyncMock()

    dispatch_mock = AsyncMock(return_value={"zcc_engagement_id": "eng-123"})

    with patch.object(_bolt_app_mod, "dispatch_zcc_outbound_call", new=dispatch_mock):
        with patch.object(_bolt_app_mod, "publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": ""}):
                await handle_outreach_approve(ack=AsyncMock(), body=_body(), client=mock_client)

    dispatch_mock.assert_awaited_once()
