"""Tests for Phase 4 Bolt action handlers: outreach approve and reject."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_body(action_id: str, draft_id: str = "draft-abc123") -> dict:
    return {
        "actions": [{"action_id": action_id, "value": draft_id}],
        "user": {"id": "U_ACTOR"},
        "container": {"channel_id": "C_CHANNEL", "message_ts": "1234567890.123456"},
    }


def _make_mock_result_with_row(row_data: dict | None) -> MagicMock:
    """Return mock SQLAlchemy result with fetchone() returning a dict-like object or None."""
    result = MagicMock()
    if row_data is not None:
        row = MagicMock()
        row._mapping = row_data
        # Support attribute access like row.draft_id
        for k, v in row_data.items():
            setattr(row, k, v)
        result.fetchone.return_value = row
    else:
        result.fetchone.return_value = None
    return result


# ---------------------------------------------------------------------------
# outreach_approve: ack first
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_approve_acks_first():
    """ack() must be called before any DB or ZCC I/O."""
    call_log: list[str] = []

    async def tracking_ack():
        call_log.append("ack")

    row_data = {
        "draft_id": "draft-abc123",
        "task_id": "task-xyz",
        "patient_id": "patient-hash-123",
        "alert_id": "alert-abc",
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        side_effect=lambda *a, **kw: (call_log.append("db"), _make_mock_result_with_row(row_data))[1]
    )
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)
    mock_publisher = AsyncMock()
    mock_client = AsyncMock()
    mock_client.chat_postEphemeral = AsyncMock()
    mock_client.chat_update = AsyncMock(side_effect=lambda **kw: call_log.append("chat_update"))

    from src.bolt_app import handle_outreach_approve, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    with patch("src.bolt_app.dispatch_zcc_outbound_call", new=AsyncMock(return_value={"stubbed": True})):
        with patch("src.bolt_app.publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": "", "ZCC_ACCOUNT_ID": "", "ZCC_CLIENT_ID": "", "ZCC_CLIENT_SECRET": "", "ZCC_DEFAULT_QUEUE_ID": ""}):
                await handle_outreach_approve(
                    ack=tracking_ack,
                    body=_make_body("outreach_approve"),
                    client=mock_client,
                )

    assert call_log[0] == "ack", f"ack() was not first; order was {call_log}"


# ---------------------------------------------------------------------------
# outreach_approve: marks draft approved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_approve_marks_draft_approved():
    """UPDATE ai_drafts SET status='approved' is executed when approve is pressed."""
    row_data = {
        "draft_id": "draft-abc123",
        "task_id": "task-xyz",
        "patient_id": "patient-hash-123",
        "alert_id": "alert-abc",
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result_with_row(row_data))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)
    mock_publisher = AsyncMock()
    mock_client = AsyncMock()

    from src.bolt_app import handle_outreach_approve, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    with patch("src.bolt_app.dispatch_zcc_outbound_call", new=AsyncMock(return_value={"stubbed": True})):
        with patch("src.bolt_app.publish_ai_event", new=AsyncMock()):
            with patch.dict("os.environ", {"PHI_STORE_URL": "", "ZCC_ACCOUNT_ID": "", "ZCC_CLIENT_ID": "", "ZCC_CLIENT_SECRET": "", "ZCC_DEFAULT_QUEUE_ID": ""}):
                await handle_outreach_approve(
                    ack=AsyncMock(),
                    body=_make_body("outreach_approve", draft_id="draft-abc123"),
                    client=mock_client,
                )

    # The SQL should have been executed
    mock_session.execute.assert_awaited()
    sql_call = mock_session.execute.call_args_list[0]
    sql_text = str(sql_call.args[0].text if hasattr(sql_call.args[0], 'text') else sql_call.args[0])
    assert "approved" in sql_text.lower()
    assert "ai_drafts" in sql_text.lower()


# ---------------------------------------------------------------------------
# outreach_approve: publishes ai.output.approved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_approve_publishes_ai_output_approved_event():
    """publish_ai_event called with event_type='ai.output.approved', draft_id, actor_id."""
    row_data = {
        "draft_id": "draft-abc123",
        "task_id": "task-xyz",
        "patient_id": "patient-hash-123",
        "alert_id": "alert-abc",
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result_with_row(row_data))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)
    mock_publisher = AsyncMock()
    mock_client = AsyncMock()

    from src.bolt_app import handle_outreach_approve, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    captured_calls = []

    async def capture_publish_ai_event(publisher, event_type, task_id, patient_id, payload):
        captured_calls.append({
            "event_type": event_type,
            "task_id": task_id,
            "payload": payload,
        })

    with patch("src.bolt_app.dispatch_zcc_outbound_call", new=AsyncMock(return_value={"stubbed": True})):
        with patch("src.bolt_app.publish_ai_event", new=capture_publish_ai_event):
            with patch.dict("os.environ", {"PHI_STORE_URL": "", "ZCC_ACCOUNT_ID": "", "ZCC_CLIENT_ID": "", "ZCC_CLIENT_SECRET": "", "ZCC_DEFAULT_QUEUE_ID": ""}):
                await handle_outreach_approve(
                    ack=AsyncMock(),
                    body=_make_body("outreach_approve", draft_id="draft-abc123"),
                    client=mock_client,
                )

    approved_events = [c for c in captured_calls if c["event_type"] == "ai.output.approved"]
    assert len(approved_events) >= 1
    event = approved_events[0]
    assert event["payload"]["draft_id"] == "draft-abc123"
    assert event["payload"]["actor_id"] == "U_ACTOR"


# ---------------------------------------------------------------------------
# outreach_reject: ack first
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_reject_acks_first():
    """ack() must be called before any DB I/O in handle_outreach_reject."""
    call_log: list[str] = []

    async def tracking_ack():
        call_log.append("ack")

    row_data = {"draft_id": "draft-abc123"}

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        side_effect=lambda *a, **kw: (call_log.append("db"), _make_mock_result_with_row(row_data))[1]
    )
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)
    mock_publisher = AsyncMock()
    mock_client = AsyncMock()
    mock_client.chat_update = AsyncMock(side_effect=lambda **kw: call_log.append("chat_update"))

    from src.bolt_app import handle_outreach_reject, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    with patch("src.bolt_app.publish_ai_event", new=AsyncMock()):
        await handle_outreach_reject(
            ack=tracking_ack,
            body=_make_body("outreach_reject"),
            client=mock_client,
        )

    assert call_log[0] == "ack", f"ack() was not first; order was {call_log}"


# ---------------------------------------------------------------------------
# outreach_reject: marks draft rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_reject_marks_draft_rejected():
    """UPDATE ai_drafts SET status='rejected' is executed when reject is pressed."""
    row_data = {"draft_id": "draft-abc123"}

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result_with_row(row_data))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)
    mock_publisher = AsyncMock()
    mock_client = AsyncMock()

    from src.bolt_app import handle_outreach_reject, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    with patch("src.bolt_app.publish_ai_event", new=AsyncMock()):
        await handle_outreach_reject(
            ack=AsyncMock(),
            body=_make_body("outreach_reject", draft_id="draft-abc123"),
            client=mock_client,
        )

    mock_session.execute.assert_awaited()
    sql_call = mock_session.execute.call_args_list[0]
    sql_text = str(sql_call.args[0].text if hasattr(sql_call.args[0], 'text') else sql_call.args[0])
    assert "rejected" in sql_text.lower()
    assert "ai_drafts" in sql_text.lower()


# ---------------------------------------------------------------------------
# outreach_reject: publishes ai.output.rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outreach_reject_publishes_ai_output_rejected_event():
    """publish_ai_event called with event_type='ai.output.rejected', draft_id, actor_id."""
    row_data = {"draft_id": "draft-abc123", "task_id": "task-xyz", "patient_id": "patient-hash"}

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=_make_mock_result_with_row(row_data))
    mock_session.commit = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)
    mock_publisher = AsyncMock()
    mock_client = AsyncMock()

    from src.bolt_app import handle_outreach_reject, set_publisher, set_session_maker

    set_session_maker(mock_session_maker)
    set_publisher(mock_publisher)

    captured_calls = []

    async def capture_publish_ai_event(publisher, event_type, task_id, patient_id, payload):
        captured_calls.append({
            "event_type": event_type,
            "task_id": task_id,
            "payload": payload,
        })

    with patch("src.bolt_app.publish_ai_event", new=capture_publish_ai_event):
        await handle_outreach_reject(
            ack=AsyncMock(),
            body=_make_body("outreach_reject", draft_id="draft-abc123"),
            client=mock_client,
        )

    rejected_events = [c for c in captured_calls if c["event_type"] == "ai.output.rejected"]
    assert len(rejected_events) >= 1
    event = rejected_events[0]
    assert event["payload"]["draft_id"] == "draft-abc123"
    assert event["payload"]["actor_id"] == "U_ACTOR"


# ---------------------------------------------------------------------------
# outreach_draft_card structure
# ---------------------------------------------------------------------------

def test_outreach_draft_card_structure():
    """outreach_draft_card returns blocks with AI: header text and approve/reject actions."""
    from src.cards import outreach_draft_card

    blocks = outreach_draft_card(
        task_id="task-abc",
        draft_id="draft-xyz",
        draft_text="Patient has elevated glucose. Please follow up.",
    )

    # Must have section block with "AI: Outreach Draft"
    section_blocks = [b for b in blocks if b.get("type") == "section"]
    assert any("AI: Outreach Draft" in b.get("text", {}).get("text", "") for b in section_blocks), \
        "No section block with 'AI: Outreach Draft' found"

    # Must have actions block with approve + reject buttons
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1, "Expected exactly 1 actions block"

    action_ids = [el["action_id"] for el in action_blocks[0]["elements"]]
    assert "outreach_approve" in action_ids
    assert "outreach_reject" in action_ids


# ---------------------------------------------------------------------------
# alert_card AI label
# ---------------------------------------------------------------------------

def test_alert_card_ai_label():
    """alert_card with cited_signals uses 'AI:' label (not '🤖 AI Summary')."""
    from src.cards import alert_card

    blocks = alert_card(
        task_id="task-abc",
        patient_hash="sha256:deadbeef",
        alert_type="glucose_high",
        severity="URGENT",
        timestamp="2026-03-06T07:00:00Z",
        ai_summary="Elevated glucose detected.",
        hasura_url="http://hasura:8080",
        cited_signals=["glucose", "weight"],
    )

    ai_block = blocks[3]
    assert "AI:" in ai_block["text"]["text"], "Expected 'AI:' label in block 3"
    assert "🤖 AI Summary" not in ai_block["text"]["text"], "Old emoji label should be removed"
