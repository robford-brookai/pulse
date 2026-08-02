"""Tests for sim-driver's EventBridge publisher wiring.

sim-driver owns no transport code after task 4.11: it builds the shared
``EventBridgePublisher`` and passes catalog domain names to it. These tests assert both
halves of that — the site emits through the shared publisher, and a bus failure lands in
``failed_webhooks`` rather than propagating into the scenario run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure ocean-events is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "libs" / "ocean-events" / "src"))

from ocean_broker.catalog import EVENT_SOURCE, address_for
from ocean_broker.publisher import EventBridgePublisher
from src.models import PatientConfig, SignalConfig
from src.patient_simulator import PatientSimulator
from src.publisher import DOMAIN_ALERTS, DOMAIN_OPS, DOMAIN_SIGNALS, build_publisher
from src.scenario_engine import ScenarioEngine


def _make_patient(signals: list[SignalConfig]) -> PatientConfig:
    return PatientConfig(patient_id="sim-pt-1", source="pocar", signals=signals)


def _make_signal(**kwargs) -> SignalConfig:
    defaults = {"sim_hour": 0.0, "type": "glucose", "value": 100}
    defaults.update(kwargs)
    return SignalConfig(**defaults)


@pytest.fixture
def mock_client() -> MagicMock:
    """EventBridge client that accepts every entry."""
    client = MagicMock()
    client.put_events = MagicMock(return_value={"FailedEntryCount": 0})
    return client


@pytest.fixture
def mock_session_maker() -> MagicMock:
    """Async session maker recording the statements executed against it."""
    session = AsyncMock()
    session.execute = AsyncMock()

    begin_context = AsyncMock()
    begin_context.__aenter__ = AsyncMock(return_value=None)
    begin_context.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_context)

    class SessionContextManager:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_):
            pass

    maker = MagicMock(side_effect=SessionContextManager)
    maker._test_session = session
    return maker


def _publisher(client: MagicMock, session_maker: MagicMock | None = None) -> EventBridgePublisher:
    with patch("ocean_broker.publisher.boto3") as mock_boto3:
        mock_boto3.client.return_value = client
        pub = EventBridgePublisher(region="us-east-1", db_session_maker=session_maker)
    pub._client = client
    return pub


class TestDomainConstants:
    """The domains sim-driver publishes to are live catalog domains, not Kafka topics."""

    @pytest.mark.parametrize("domain", [DOMAIN_SIGNALS, DOMAIN_ALERTS, DOMAIN_OPS])
    def test_domain_is_addressable(self, domain: str) -> None:
        address = address_for(domain)
        assert address.source == EVENT_SOURCE
        assert address.detail_type == domain

    @pytest.mark.parametrize("domain", [DOMAIN_SIGNALS, DOMAIN_ALERTS, DOMAIN_OPS])
    def test_domain_is_not_a_topic_name(self, domain: str) -> None:
        """`ocean.signals` is the retired topic name and addresses to nothing."""
        assert not domain.startswith("ocean.")


class TestBuildPublisher:
    """build_publisher wires the shared publisher, with the DLQ only when configured."""

    def test_returns_shared_publisher(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch("ocean_broker.publisher.boto3"):
            pub = build_publisher()
        assert isinstance(pub, EventBridgePublisher)

    def test_no_database_url_means_no_dlq(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with patch("ocean_broker.publisher.boto3"):
            pub = build_publisher()
        assert pub._db_session_maker is None

    def test_database_url_wires_the_dlq(self) -> None:
        with patch("ocean_broker.publisher.boto3"), patch("src.publisher.create_async_engine") as mock_engine:
            pub = build_publisher(database_url="postgresql+asyncpg://u:p@db/ocean")
        assert mock_engine.call_count == 1
        assert pub._db_session_maker is not None


class TestEmitsThroughSharedPublisher:
    """Every sim-driver publish site goes through EventBridgePublisher."""

    @pytest.mark.asyncio
    async def test_signal_addresses_to_signals_domain(self, mock_client) -> None:
        sim = PatientSimulator("scn", _make_patient([_make_signal()]), _publisher(mock_client), 960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        entry = mock_client.put_events.call_args_list[0].kwargs["Entries"][0]
        assert entry["Source"] == EVENT_SOURCE
        assert entry["DetailType"] == DOMAIN_SIGNALS

    @pytest.mark.asyncio
    async def test_alert_addresses_to_alerts_domain(self, mock_client) -> None:
        sim = PatientSimulator("scn", _make_patient([_make_signal(anomalous=True)]), _publisher(mock_client), 960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        detail_types = [c.kwargs["Entries"][0]["DetailType"] for c in mock_client.put_events.call_args_list]
        assert detail_types == [DOMAIN_SIGNALS, DOMAIN_ALERTS]

    @pytest.mark.asyncio
    async def test_bookends_address_to_ops_domain(self, mock_client) -> None:
        engine = ScenarioEngine(scenario_name="smoke_test", publisher=_publisher(mock_client))

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await engine.run()

        entries = [c.kwargs["Entries"][0] for c in mock_client.put_events.call_args_list]
        ops_types = [json.loads(e["Detail"])["event_type"] for e in entries if e["DetailType"] == DOMAIN_OPS]
        assert ops_types == ["scenario.started", "scenario.completed"]

    @pytest.mark.asyncio
    async def test_envelope_is_carried_whole(self, mock_client) -> None:
        """detail-type is the domain; the envelope's event_type is untouched inside detail."""
        sim = PatientSimulator("scn", _make_patient([_make_signal()]), _publisher(mock_client), 960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        entry = mock_client.put_events.call_args_list[0].kwargs["Entries"][0]
        envelope = json.loads(entry["Detail"])
        assert envelope["event_type"] == "signal.received"
        assert envelope["source_system"] == "pocar"
        assert envelope["payload"]["patient_id"] == "sim-pt-1"


class TestFailurePath:
    """A bus failure writes failed_webhooks and does not break the scenario run."""

    @pytest.mark.asyncio
    async def test_bus_failure_writes_failed_webhooks(self, mock_client, mock_session_maker) -> None:
        mock_client.put_events = MagicMock(side_effect=RuntimeError("bus unreachable"))
        pub = _publisher(mock_client, mock_session_maker)
        sim = PatientSimulator("scn", _make_patient([_make_signal()]), pub, 960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        execute = mock_session_maker._test_session.execute
        assert execute.call_count == 1
        statement, params = execute.call_args.args
        assert "failed_webhooks" in str(statement)
        assert params["error"] == "bus unreachable"
        assert json.loads(params["payload"])["event_type"] == "signal.received"

    @pytest.mark.asyncio
    async def test_bus_failure_does_not_raise(self, mock_client, mock_session_maker) -> None:
        mock_client.put_events = MagicMock(side_effect=RuntimeError("bus unreachable"))
        pub = _publisher(mock_client, mock_session_maker)
        sim = PatientSimulator("scn", _make_patient([_make_signal(anomalous=True)]), pub, 960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        # Both events attempted despite the first failing.
        assert mock_client.put_events.call_count == 2
        assert mock_session_maker._test_session.execute.call_count == 2
