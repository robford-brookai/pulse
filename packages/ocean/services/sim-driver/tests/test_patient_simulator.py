"""Tests for PatientSimulator: event construction, schema conformance, severity, timing."""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Ensure ocean-events is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "libs" / "ocean-events" / "src"))

from ocean_events.base import BaseEvent
from src.models import PatientConfig, SignalConfig
from src.patient_simulator import PatientSimulator


def _make_patient(
    signals: list[SignalConfig],
    patient_id: str = "p1",
    source: str = "pocar",
) -> PatientConfig:
    return PatientConfig(patient_id=patient_id, source=source, signals=signals)


def _make_signal(**kwargs) -> SignalConfig:
    defaults = {"sim_hour": 0.0, "type": "glucose", "value": 100}
    defaults.update(kwargs)
    return SignalConfig(**defaults)


def _deterministic_id(scenario: str, patient_id: str, idx: int, suffix: str = "") -> uuid.UUID:
    """Mirror the expected deterministic ID generation."""
    key = f"sim:{scenario}:{patient_id}:{idx}{suffix}"
    return uuid.UUID(bytes=hashlib.sha256(key.encode()).digest()[:16])


class TestEventTypes:
    """Only signal.received and alert.created events are published."""

    @pytest.mark.asyncio
    async def test_publishes_signal_received(self) -> None:
        sig = _make_signal()
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        assert pub.publish.call_count == 1
        topic, event = pub.publish.call_args_list[0].args
        assert topic == "ocean.signals"
        assert event["event_type"] == "signal.received"

    @pytest.mark.asyncio
    async def test_publishes_alert_for_anomalous(self) -> None:
        sig = _make_signal(anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        assert pub.publish.call_count == 2
        topics = [call.args[0] for call in pub.publish.call_args_list]
        types = [call.args[1]["event_type"] for call in pub.publish.call_args_list]
        assert topics == ["ocean.signals", "ocean.alerts"]
        assert types == ["signal.received", "alert.created"]

    @pytest.mark.asyncio
    async def test_no_alert_for_non_anomalous(self) -> None:
        sig = _make_signal(anomalous=False)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        assert pub.publish.call_count == 1
        assert pub.publish.call_args_list[0].args[1]["event_type"] == "signal.received"


class TestDeterministicIds:
    """Event IDs are SHA-256 based and deterministic."""

    @pytest.mark.asyncio
    async def test_signal_event_id_is_deterministic(self) -> None:
        sig = _make_signal()
        patient = _make_patient([sig], patient_id="px")
        pub = AsyncMock()
        sim = PatientSimulator("demo", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        event = pub.publish.call_args_list[0].args[1]
        expected = str(_deterministic_id("demo", "px", 0))
        assert event["event_id"] == expected

    @pytest.mark.asyncio
    async def test_alert_event_id_uses_alert_suffix(self) -> None:
        sig = _make_signal(anomalous=True)
        patient = _make_patient([sig], patient_id="px")
        pub = AsyncMock()
        sim = PatientSimulator("demo", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        alert_event = pub.publish.call_args_list[1].args[1]
        expected = str(_deterministic_id("demo", "px", 0, "_alert"))
        assert alert_event["event_id"] == expected

    @pytest.mark.asyncio
    async def test_signal_and_alert_ids_differ(self) -> None:
        sig = _make_signal(anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        signal_id = pub.publish.call_args_list[0].args[1]["event_id"]
        alert_id = pub.publish.call_args_list[1].args[1]["event_id"]
        assert signal_id != alert_id


class TestSourceSystem:
    """source_system reflects resolved source, never 'sim-driver'."""

    @pytest.mark.asyncio
    async def test_source_from_patient_default(self) -> None:
        sig = _make_signal()
        patient = _make_patient([sig], source="pocar")
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        event = pub.publish.call_args_list[0].args[1]
        assert event["source_system"] == "pocar"

    @pytest.mark.asyncio
    async def test_source_from_signal_override(self) -> None:
        sig = _make_signal(source="impilo")
        patient = _make_patient([sig], source="pocar")
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        event = pub.publish.call_args_list[0].args[1]
        assert event["source_system"] == "impilo"

    @pytest.mark.asyncio
    async def test_source_never_sim_driver(self) -> None:
        sig = _make_signal()
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        for call in pub.publish.call_args_list:
            assert call.args[1]["source_system"] != "sim-driver"


class TestCorrelationId:
    """correlation_id has sim- prefix for traceability."""

    @pytest.mark.asyncio
    async def test_correlation_id_starts_with_sim(self) -> None:
        sig = _make_signal(anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        for call in pub.publish.call_args_list:
            assert call.args[1]["correlation_id"].startswith("sim-")


class TestPayloadFields:
    """Verify signal and alert payload contents."""

    @pytest.mark.asyncio
    async def test_signal_payload(self) -> None:
        sig = _make_signal(value=120, unit="mg/dL", anomalous=False)
        patient = _make_patient([sig], patient_id="p1")
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        payload = pub.publish.call_args_list[0].args[1]["payload"]
        assert payload["patient_id"] == "p1"
        assert payload["clinic_id"] == "clinic-demo"
        assert payload["signal_type"] == "glucose"
        assert payload["value"] == 120
        assert payload["unit"] == "mg/dL"
        assert payload["anomalous"] is False
        assert "signal_id" in payload

    @pytest.mark.asyncio
    async def test_alert_payload(self) -> None:
        sig = _make_signal(value=350, anomalous=True, severity_hint="CRITICAL")
        patient = _make_patient([sig], patient_id="p1")
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        payload = pub.publish.call_args_list[1].args[1]["payload"]
        assert payload["alert_type"] == "glucose_anomaly"
        assert payload["severity"] == "CRITICAL"
        assert payload["patient_id"] == "p1"
        assert payload["clinic_id"] == "clinic-demo"
        assert payload["signal_type"] == "glucose"
        assert payload["signal_value"] == 350


class TestSeverityInference:
    """severity_hint overrides value-based inference."""

    @pytest.mark.asyncio
    async def test_severity_hint_overrides_inference(self) -> None:
        # Low glucose wouldn't normally be CRITICAL, but hint forces it
        sig = _make_signal(value=80, anomalous=True, severity_hint="CRITICAL")
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        payload = pub.publish.call_args_list[1].args[1]["payload"]
        assert payload["severity"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_infer_critical_glucose(self) -> None:
        sig = _make_signal(type="glucose", value=350, anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        payload = pub.publish.call_args_list[1].args[1]["payload"]
        assert payload["severity"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_infer_urgent_spo2(self) -> None:
        sig = _make_signal(type="spo2", value=85, anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        payload = pub.publish.call_args_list[1].args[1]["payload"]
        assert payload["severity"] == "URGENT"

    @pytest.mark.asyncio
    async def test_infer_high_default(self) -> None:
        sig = _make_signal(type="heart_rate", value=110, anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        payload = pub.publish.call_args_list[1].args[1]["payload"]
        assert payload["severity"] == "HIGH"


class TestTimingAndSleep:
    """sim_sleep called with correct delay between signals."""

    @pytest.mark.asyncio
    async def test_sim_sleep_called_with_delay(self) -> None:
        sigs = [
            _make_signal(sim_hour=0.0),
            _make_signal(sim_hour=1.5, type="spo2", value=95),
        ]
        patient = _make_patient(sigs)
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock) as mock_sleep:
            await sim.run()

        # First signal at t=0 sleeps 0 hours
        assert mock_sleep.call_args_list[0].args == (0.0, 960)
        # Second signal at t=1.5 sleeps 1.5 hours from previous
        assert mock_sleep.call_args_list[1].args == (1.5, 960)


class TestExpectedEventCount:
    """expected_event_count = total signals + anomalous count."""

    def test_no_anomalous(self) -> None:
        sigs = [_make_signal(), _make_signal(sim_hour=1.0)]
        patient = _make_patient(sigs)
        sim = PatientSimulator("scn", patient, AsyncMock(), compression_ratio=960)
        assert sim.expected_event_count == 2

    def test_with_anomalous(self) -> None:
        sigs = [
            _make_signal(),
            _make_signal(sim_hour=1.0, anomalous=True),
            _make_signal(sim_hour=2.0, anomalous=True),
        ]
        patient = _make_patient(sigs)
        sim = PatientSimulator("scn", patient, AsyncMock(), compression_ratio=960)
        # 3 signals + 2 alerts = 5
        assert sim.expected_event_count == 5


class TestBaseEventConformance:
    """Published events are valid BaseEvent instances when deserialized."""

    @pytest.mark.asyncio
    async def test_signal_event_is_valid_base_event(self) -> None:
        sig = _make_signal()
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        event_dict = pub.publish.call_args_list[0].args[1]
        # Should not raise -- validates BaseEvent schema conformance
        BaseEvent(**event_dict)

    @pytest.mark.asyncio
    async def test_alert_event_is_valid_base_event(self) -> None:
        sig = _make_signal(anomalous=True)
        patient = _make_patient([sig])
        pub = AsyncMock()
        sim = PatientSimulator("scn", patient, pub, compression_ratio=960)

        with patch("src.patient_simulator.sim_sleep", new_callable=AsyncMock):
            await sim.run()

        event_dict = pub.publish.call_args_list[1].args[1]
        BaseEvent(**event_dict)
