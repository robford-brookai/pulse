"""PTLN-03: Extended patient command with consolidated timeline view."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

SERVICES_ROOT = Path(__file__).resolve().parents[2] / "services" / "slack-bot"
SLASH_COMMANDS_PATH = SERVICES_ROOT / "src" / "slash_commands.py"


def _read_source() -> str:
    return SLASH_COMMANDS_PATH.read_text()


# ---------------------------------------------------------------------------
# Source-inspection tests
# ---------------------------------------------------------------------------


class TestPTLN03SourceInspection:
    """Verify build_patient_response queries patient_timeline view."""

    def test_queries_patient_timeline_view(self):
        """build_patient_response must query patient_timeline (not N separate tables)."""
        source = _read_source()
        assert "patient_timeline" in source, "build_patient_response should query patient_timeline view"

    def test_summary_includes_open_tickets(self):
        source = _read_source()
        assert "Open Tickets" in source

    def test_summary_includes_active_devices(self):
        source = _read_source()
        assert "Active Devices" in source

    def test_summary_includes_pending_fulfillments(self):
        source = _read_source()
        assert "Pending Fulfillments" in source

    def test_summary_includes_last_rma(self):
        source = _read_source()
        assert "Last RMA" in source

    def test_emoji_prefix_ticket(self):
        source = _read_source()
        assert ":ticket:" in source

    def test_emoji_prefix_package(self):
        source = _read_source()
        assert ":package:" in source

    def test_emoji_prefix_electric_plug(self):
        source = _read_source()
        assert ":electric_plug:" in source

    def test_emoji_prefix_leftwards_arrow(self):
        source = _read_source()
        assert ":leftwards_arrow_with_hook:" in source

    def test_emoji_prefix_rotating_light(self):
        source = _read_source()
        assert ":rotating_light:" in source

    def test_emoji_prefix_clipboard(self):
        source = _read_source()
        assert ":clipboard:" in source

    def test_emoji_prefix_telephone(self):
        source = _read_source()
        assert ":telephone_receiver:" in source

    def test_emoji_prefix_chart(self):
        source = _read_source()
        assert ":chart_with_upwards_trend:" in source

    def test_timeline_truncation_cap(self):
        """Timeline should be capped at 30 entries."""
        source = _read_source()
        # Should reference a max/limit of 30 for timeline display
        assert re.search(r"\b30\b", source), "Timeline should cap at 30 entries"

    def test_help_mentions_patient_timeline(self):
        """Help response should mention patient command with timeline."""
        source = _read_source()
        assert "patient" in source.lower()
        assert "timeline" in source.lower()


# ---------------------------------------------------------------------------
# Unit tests (import-based with mocked Hasura)
# ---------------------------------------------------------------------------


def _import_slash_commands():
    """Import slash_commands module from source path."""
    import importlib.util
    import sys

    service_dir = str(SERVICES_ROOT)
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    keys_to_remove = [k for k in sys.modules if k.startswith("src.slash_commands")]
    for k in keys_to_remove:
        del sys.modules[k]

    spec = importlib.util.spec_from_file_location("src.slash_commands", SLASH_COMMANDS_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["src.slash_commands"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def _clear_slash_modules():
    import sys

    keys_to_remove = [k for k in sys.modules if "slash_commands" in k]
    for k in keys_to_remove:
        del sys.modules[k]
    yield
    keys_to_remove = [k for k in sys.modules if "slash_commands" in k]
    for k in keys_to_remove:
        del sys.modules[k]


SAMPLE_HASURA_RESPONSE = {
    "data": {
        "patients": [{"patient_id": "P001", "enrollment_status": "active"}],
        "patient_timeline": [
            {
                "event_type": "alert",
                "event_id": "a1",
                "status": "open",
                "summary": "High BP reading",
                "created_at": "2026-03-10T10:00:00Z",
            },
            {
                "event_type": "task",
                "event_id": "t1",
                "status": "open",
                "summary": "Follow up call",
                "created_at": "2026-03-10T09:00:00Z",
            },
            {
                "event_type": "ticket",
                "event_id": "tk1",
                "status": "open",
                "summary": "Device issue reported",
                "created_at": "2026-03-09T15:00:00Z",
            },
            {
                "event_type": "ticket",
                "event_id": "tk2",
                "status": "resolved",
                "summary": "Activation complete",
                "created_at": "2026-03-08T10:00:00Z",
            },
            {
                "event_type": "fulfillment",
                "event_id": "f1",
                "status": "shipped",
                "summary": "BP cuff shipment",
                "created_at": "2026-03-07T12:00:00Z",
            },
            {
                "event_type": "return",
                "event_id": "r1",
                "status": "received",
                "summary": "RMA for defective scale",
                "created_at": "2026-03-06T08:00:00Z",
            },
            {
                "event_type": "device",
                "event_id": "d1",
                "status": "associated",
                "summary": "BP Monitor (SN-123)",
                "created_at": "2026-03-05T14:00:00Z",
            },
            {
                "event_type": "device",
                "event_id": "d2",
                "status": "associated",
                "summary": "Scale (SN-456)",
                "created_at": "2026-03-04T11:00:00Z",
            },
            {
                "event_type": "interaction",
                "event_id": "i1",
                "status": "completed",
                "summary": "Outbound call - connected",
                "created_at": "2026-03-03T16:00:00Z",
            },
            {
                "event_type": "signal",
                "event_id": "s1",
                "status": "active",
                "summary": "weight=185",
                "created_at": "2026-03-02T08:00:00Z",
            },
        ],
    }
}


class TestBuildPatientResponseUnit:
    """Unit tests for build_patient_response with mocked Hasura."""

    @pytest.mark.asyncio
    async def test_summary_card_has_open_tickets(self, _clear_slash_modules):
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        text = str(blocks)
        assert "Open Tickets" in text

    @pytest.mark.asyncio
    async def test_summary_card_has_active_devices(self, _clear_slash_modules):
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        text = str(blocks)
        assert "Active Devices" in text

    @pytest.mark.asyncio
    async def test_summary_card_has_pending_fulfillments(self, _clear_slash_modules):
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        text = str(blocks)
        assert "Pending Fulfillments" in text

    @pytest.mark.asyncio
    async def test_summary_card_has_last_rma(self, _clear_slash_modules):
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        text = str(blocks)
        assert "Last RMA" in text

    @pytest.mark.asyncio
    async def test_timeline_has_emoji_prefixes(self, _clear_slash_modules):
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        text = str(blocks)
        assert ":rotating_light:" in text
        assert ":clipboard:" in text
        assert ":ticket:" in text
        assert ":package:" in text
        assert ":electric_plug:" in text

    @pytest.mark.asyncio
    async def test_open_tickets_count(self, _clear_slash_modules):
        """Open Tickets count should be 1 (tk1 is open)."""
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        # Find the summary section text
        summary_text = ""
        for block in blocks:
            t = block.get("text", {}).get("text", "")
            if "Open Tickets" in t:
                summary_text = t
                break
        assert "1" in summary_text, f"Expected Open Tickets: 1, got: {summary_text}"

    @pytest.mark.asyncio
    async def test_active_devices_count(self, _clear_slash_modules):
        """Active Devices count should be 2 (d1 and d2 are associated)."""
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        summary_text = ""
        for block in blocks:
            t = block.get("text", {}).get("text", "")
            if "Active Devices" in t:
                summary_text = t
                break
        assert "2" in summary_text, f"Expected Active Devices: 2, got: {summary_text}"

    @pytest.mark.asyncio
    async def test_pending_fulfillments_count(self, _clear_slash_modules):
        """Pending Fulfillments count should be 1 (f1 is shipped, not delivered/cancelled)."""
        mod = _import_slash_commands()
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = SAMPLE_HASURA_RESPONSE
            blocks = await mod.build_patient_response("P001")

        summary_text = ""
        for block in blocks:
            t = block.get("text", {}).get("text", "")
            if "Pending Fulfillments" in t:
                summary_text = t
                break
        assert "1" in summary_text, f"Expected Pending Fulfillments: 1, got: {summary_text}"

    @pytest.mark.asyncio
    async def test_no_patient_found(self, _clear_slash_modules):
        """Returns not-found message when patient doesn't exist."""
        mod = _import_slash_commands()
        empty_response = {"data": {"patients": [], "patient_timeline": []}}
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = empty_response
            blocks = await mod.build_patient_response("PXXX")

        text = str(blocks)
        assert "No patient found" in text

    @pytest.mark.asyncio
    async def test_truncation_shows_overflow_message(self, _clear_slash_modules):
        """When timeline > 30 entries, show overflow message."""
        mod = _import_slash_commands()
        # Create 35 timeline entries
        timeline_entries = [
            {
                "event_type": "signal",
                "event_id": f"s{i}",
                "status": "active",
                "summary": f"val={i}",
                "created_at": f"2026-03-{10 - i // 30:02d}T{i % 24:02d}:00:00Z",
            }
            for i in range(35)
        ]
        big_response = {
            "data": {
                "patients": [{"patient_id": "P001", "enrollment_status": "active"}],
                "patient_timeline": timeline_entries,
            }
        }
        with patch.object(mod, "_hasura_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = big_response
            blocks = await mod.build_patient_response("P001")

        text = str(blocks)
        assert "35" in text, "Should show total count of 35"
        assert "30" in text, "Should mention showing 30 entries"
