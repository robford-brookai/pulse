"""Tests for /ocean patient status rendering — citation-aware, per m1-retire-patient-state.

The Hasura query must select ledger_seq alongside enrollment_status, and the
*Status:* line must mark a null citation as legacy rather than presenting the
value as a verified status (spec: "The read surfaces present the projected
state and its citation").
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from src.slash_commands import build_patient_response


def _hasura_result(patient: dict, timeline: list | None = None) -> dict:
    return {
        "data": {
            "patients": [patient],
            "patient_timeline": timeline or [],
        }
    }


@pytest.mark.asyncio
async def test_patient_query_selects_ledger_seq():
    """The GetPatientTimeline query selects ledger_seq, not just enrollment_status."""
    mock_query = AsyncMock(
        return_value=_hasura_result({"patient_id": "p-1", "enrollment_status": "active", "ledger_seq": 50})
    )
    with patch("src.slash_commands._hasura_query", mock_query):
        await build_patient_response("p-1")

    query_text = mock_query.call_args[0][0]
    assert "ledger_seq" in query_text


@pytest.mark.asyncio
async def test_projected_row_shows_status_with_no_legacy_marker():
    """A row citing a ledger_seq renders its catalog state with no legacy marker."""
    mock_query = AsyncMock(
        return_value=_hasura_result({"patient_id": "p-1", "enrollment_status": "on_hold", "ledger_seq": 88})
    )
    with patch("src.slash_commands._hasura_query", mock_query):
        blocks = await build_patient_response("p-1")

    summary_text = blocks[1]["text"]["text"]
    assert "*Status:* on_hold" in summary_text
    assert "legacy" not in summary_text.lower()


@pytest.mark.asyncio
async def test_legacy_row_marked_and_unverified():
    """A row with a null ledger_seq is marked legacy and unverified, not presented as status."""
    mock_query = AsyncMock(
        return_value=_hasura_result({"patient_id": "p-1", "enrollment_status": "pending", "ledger_seq": None})
    )
    with patch("src.slash_commands._hasura_query", mock_query):
        blocks = await build_patient_response("p-1")

    summary_text = blocks[1]["text"]["text"]
    assert "legacy" in summary_text.lower()
    assert "unverified" in summary_text.lower()
