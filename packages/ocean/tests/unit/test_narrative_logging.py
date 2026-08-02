"""Tests for narrative logging across all sim services.

Verifies that each service emits human-readable log lines with distinctive
prefixes ([SIM], [TASK], [CLAIM], [AI], [GATE], [CALL]) alongside existing
structured log calls.

Uses importlib for direct file imports to avoid src/ namespace collisions
between services that all use flat `src/` package layouts.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

from structlog.testing import capture_logs

_ROOT = Path(__file__).resolve().parents[2]
_EVENTS_LIB = _ROOT / "libs" / "ocean-events" / "src"

# ocean-events must be importable for all services
if str(_EVENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_EVENTS_LIB))


def _load_module(name: str, file_path: Path, deps: dict[str, ModuleType] | None = None) -> ModuleType:
    """Load a Python module from an absolute file path.

    Temporarily injects dependency modules into sys.modules so that
    intra-package imports (e.g., `from src.models import ...`) resolve
    from the correct service directory.
    """
    spec = importlib.util.spec_from_file_location(name, file_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)

    # Inject service-level src package so `from src.X import Y` works
    svc_root = file_path.parent.parent  # e.g., services/sim-driver
    if str(svc_root) not in sys.path:
        sys.path.insert(0, str(svc_root))

    saved = {}
    if deps:
        for dep_name, dep_mod in deps.items():
            saved[dep_name] = sys.modules.get(dep_name)
            sys.modules[dep_name] = dep_mod

    try:
        spec.loader.exec_module(mod)
    finally:
        for dep_name in saved:
            if saved[dep_name] is None:
                sys.modules.pop(dep_name, None)
            else:
                sys.modules[dep_name] = saved[dep_name]

    return mod


# ── sim-driver ──────────────────────────────────────────────────


class TestSimDriverNarrative:
    """PatientSimulator emits [SIM] narrative lines for signals and alerts."""

    def _get_simulator(self):
        """Import PatientSimulator and models from sim-driver service."""
        svc = _ROOT / "services" / "sim-driver"
        if str(svc) not in sys.path:
            sys.path.insert(0, str(svc))

        # Clear any cached src modules from other services
        to_remove = [k for k in sys.modules if k.startswith("src.")]
        for k in to_remove:
            del sys.modules[k]
        sys.modules.pop("src", None)

        from src.models import PatientConfig, SignalConfig
        from src.patient_simulator import PatientSimulator

        return PatientSimulator, PatientConfig, SignalConfig

    async def test_sim_driver_signal_narrative(self):
        PatientSimulator, PatientConfig, SignalConfig = self._get_simulator()

        patient = PatientConfig(
            patient_id="P-001",
            clinic_id="clinic-demo",
            signals=[
                SignalConfig(sim_hour=0.0, type="glucose", value=110, unit="mg/dL"),
            ],
        )
        publisher = AsyncMock()
        sim = PatientSimulator("test-scenario", patient, publisher, compression_ratio=1e9)

        with capture_logs() as cap:
            await sim.run()

        narrative = [e for e in cap if "[SIM]" in str(e.get("event", ""))]
        assert len(narrative) >= 1, f"Expected [SIM] narrative line, got: {cap}"
        line = narrative[0]["event"]
        assert "P-001" in line
        assert "glucose" in line
        assert "110" in line
        assert "mg/dL" in line

    async def test_sim_driver_alert_narrative(self):
        PatientSimulator, PatientConfig, SignalConfig = self._get_simulator()

        patient = PatientConfig(
            patient_id="P-002",
            clinic_id="clinic-demo",
            signals=[
                SignalConfig(
                    sim_hour=0.0,
                    type="spo2",
                    value=85,
                    unit="%",
                    anomalous=True,
                    severity_hint="URGENT",
                ),
            ],
        )
        publisher = AsyncMock()
        sim = PatientSimulator("test-scenario", patient, publisher, compression_ratio=1e9)

        with capture_logs() as cap:
            await sim.run()

        alert_lines = [e for e in cap if "[SIM]" in str(e.get("event", "")) and "ALERT" in str(e.get("event", ""))]
        assert len(alert_lines) >= 1, f"Expected [SIM] ALERT narrative, got: {cap}"
        line = alert_lines[0]["event"]
        assert "P-002" in line
        assert "spo2_anomaly" in line
        assert "URGENT" in line


# ── control-plane (source inspection) ───────────────────────────


class TestControlPlaneNarrative:
    """alerts.py contains a [TASK] narrative log line (source inspection)."""

    def test_control_plane_task_narrative(self):
        src_path = _ROOT / "services" / "control-plane" / "src" / "handlers" / "alerts.py"
        source = src_path.read_text()
        assert "[TASK]" in source, "alerts.py must contain a [TASK] narrative log line"
        assert "patient_id" in source


# ── agent-worker claim (source inspection) ──────────────────────


class TestAgentWorkerClaimNarrative:
    """claim.py contains a [CLAIM] narrative log line (source inspection)."""

    def test_agent_worker_claim_narrative(self):
        src_path = _ROOT / "services" / "agent-worker" / "src" / "claim.py"
        source = src_path.read_text()
        assert "[CLAIM]" in source, "claim.py must contain a [CLAIM] narrative log line"
        assert "patient_id" in source


# ── agent-worker decision (source inspection) ───────────────────


class TestAgentWorkerDecisionNarrative:
    """consumer.py contains [AI] and [GATE] narrative log lines."""

    def test_agent_worker_ai_narrative(self):
        src_path = _ROOT / "services" / "agent-worker" / "src" / "consumer.py"
        source = src_path.read_text()
        assert "[AI]" in source, "consumer.py must contain an [AI] narrative log line"
        assert "patient_id" in source
        assert "confidence" in source

    def test_agent_worker_gate_narrative(self):
        src_path = _ROOT / "services" / "agent-worker" / "src" / "consumer.py"
        source = src_path.read_text()
        assert "[GATE]" in source, "consumer.py must contain a [GATE] narrative log line"
        assert "APPROVED" in source or "REJECTED" in source


# ── call-simulator ──────────────────────────────────────────────


class TestCallSimNarrative:
    """simulate_call emits [CALL] narrative lines."""

    def _get_call_sim(self):
        svc = _ROOT / "services" / "call-simulator"
        if str(svc) not in sys.path:
            sys.path.insert(0, str(svc))
        to_remove = [k for k in sys.modules if k.startswith("src.")]
        for k in to_remove:
            del sys.modules[k]
        sys.modules.pop("src", None)
        from src.call_sim import simulate_call

        return simulate_call

    async def test_call_sim_started_narrative(self):
        simulate_call = self._get_call_sim()

        approval = {
            "correlation_id": "corr-4",
            "payload": {
                "patient_id": "P-006",
                "persona_id": "nurse-jane",
                "call_answer_rate": 1.0,
                "missed_call_retry_count": 0,
                "compression_ratio": 1e9,
            },
        }
        publisher = AsyncMock()

        with capture_logs() as cap:
            await simulate_call(approval, publisher)

        started_lines = [e for e in cap if "[CALL]" in str(e.get("event", "")) and "started" in str(e.get("event", ""))]
        assert len(started_lines) >= 1, f"Expected [CALL] started narrative, got: {cap}"
        assert "P-006" in started_lines[0]["event"]

    async def test_call_sim_outcome_narrative(self):
        simulate_call = self._get_call_sim()

        approval = {
            "correlation_id": "corr-5",
            "payload": {
                "patient_id": "P-007",
                "persona_id": "nurse-jane",
                "call_answer_rate": 1.0,
                "missed_call_retry_count": 0,
                "compression_ratio": 1e9,
            },
        }
        publisher = AsyncMock()

        with capture_logs() as cap:
            await simulate_call(approval, publisher)

        call_lines = [e for e in cap if "[CALL]" in str(e.get("event", ""))]
        events_text = " ".join(e["event"] for e in call_lines)
        assert "CONNECTED" in events_text or "MISSED" in events_text, (
            f"Expected CONNECTED or MISSED in [CALL] lines, got: {events_text}"
        )
        assert "P-007" in events_text
