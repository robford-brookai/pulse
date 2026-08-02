"""ZCC-01: Approved draft dispatches to ZCC.

Requirement: When a care coordinator presses "Approve & Dispatch", the system
calls the ZCC outbound call API (dispatch_zcc_outbound_call). The call includes
the task_id in user_data for engagement correlation. Dispatch is stubbed when
PHI_STORE_URL is not configured, but the call is always made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, call as mock_call

import pytest

from utils import setup_service

setup_service("slack-bot")

import src.bolt_app as _bolt_app_mod  # noqa: E402
import src.zcc_dispatch as _zcc_dispatch_mod  # noqa: E402
from src.bolt_app import handle_outreach_approve, set_publisher, set_session_maker  # noqa: E402
from src.zcc_dispatch import dispatch_zcc_outbound_call  # noqa: E402


def _body(draft_id: str = "draft-001") -> dict:
    return {
        "actions": [{"action_id": "outreach_approve", "value": draft_id}],
        "user": {"id": "U_AGENT"},
        "container": {"channel_id": "C_CHAN", "message_ts": "111.222"},
    }


def _make_row(task_id: str = "task-xyz"):
    row = MagicMock()
    row.draft_id = "draft-001"
    row.task_id = task_id
    row.patient_id = "pt-hash"
    row.alert_id = "alert-abc"
    return row


@pytest.mark.asyncio
async def test_dispatch_called_with_task_id_in_user_data():
    """dispatch_zcc_outbound_call is called with task_id for engagement correlation."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=_make_row(task_id="task-corr-001")))
    )
    mock_session.commit = AsyncMock()

    set_session_maker(MagicMock(return_value=mock_session))
    set_publisher(AsyncMock())

    dispatch_mock = AsyncMock(return_value={"zcc_engagement_id": "eng-456"})

    with patch.object(_bolt_app_mod, "dispatch_zcc_outbound_call", new=dispatch_mock):
        with patch.object(_bolt_app_mod, "publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": "", "ZCC_DEFAULT_QUEUE_ID": "queue-1"}):
                await handle_outreach_approve(
                    ack=AsyncMock(),
                    body=_body(),
                    client=AsyncMock(),
                )

    dispatch_mock.assert_awaited_once()
    _, kwargs = dispatch_mock.call_args
    assert kwargs.get("task_id") == "task-corr-001", (
        f"Expected task_id='task-corr-001' in dispatch call, got: {kwargs}"
    )


@pytest.mark.asyncio
async def test_dispatch_called_with_agent_user_id():
    """dispatch_zcc_outbound_call receives the approving coordinator's user ID."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(fetchone=MagicMock(return_value=_make_row()))
    )
    mock_session.commit = AsyncMock()

    set_session_maker(MagicMock(return_value=mock_session))
    set_publisher(AsyncMock())

    dispatch_mock = AsyncMock(return_value={"zcc_engagement_id": "eng-789"})

    with patch.object(_bolt_app_mod, "dispatch_zcc_outbound_call", new=dispatch_mock):
        with patch.object(_bolt_app_mod, "publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": ""}):
                body = _body()
                body["user"]["id"] = "U_SPECIFIC_AGENT"
                await handle_outreach_approve(
                    ack=AsyncMock(),
                    body=body,
                    client=AsyncMock(),
                )

    _, kwargs = dispatch_mock.call_args
    assert kwargs.get("agent_user_id") == "U_SPECIFIC_AGENT"


@pytest.mark.asyncio
async def test_zcc_dispatch_function_sends_make_call_action():
    """dispatch_zcc_outbound_call POSTs 'make_call' action with task_id in user_data."""
    import httpx

    captured_json: list[dict] = []

    async def mock_post(url, **kwargs):
        captured_json.append(kwargs.get("json", {}))
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"engagement_id": "eng-test"})
        return mock_resp

    with patch.object(_zcc_dispatch_mod, "httpx") as mock_httpx:
        mock_http_cls = mock_httpx.AsyncClient
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = mock_post
        mock_http_cls.return_value = mock_http

        result = await dispatch_zcc_outbound_call(
            zcc_token="test-token",
            agent_user_id="U_AGENT",
            patient_phone="+15551234567",
            queue_id="queue-abc",
            task_id="task-corr-001",
        )

    assert len(captured_json) == 1
    body = captured_json[0]
    assert body.get("action") == "make_call"
    params = body.get("params", {})
    assert params.get("user_data", {}).get("task_id") == "task-corr-001"
