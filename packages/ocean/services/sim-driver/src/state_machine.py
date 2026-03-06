"""Per-patient FSM driving the care coordination simulation loop.

States:
  idle → signal_published → alerted → task_open → task_claimed →
  outreach_pending → dispatched / rejected → resolved
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from src.clock import sim_sleep
from src.agent_runner import claim_delay_seconds, generate_outreach_decision, get_agent
from src.llm_judge import judge_action
from src.human_gate import post_human_gate

log = structlog.get_logger()

# Default compression: 8h → 30min (960x), but each SM uses the value from scenario_engine
_DEFAULT_COMPRESSION = 960

# Wait up to 5 sim-minutes for the task to be created after alert (in sim time)
_TASK_CREATION_WAIT_SIM_HOURS = 5 / 60


class PatientStateMachine:
    """Drives one patient through the full care coordination loop."""

    def __init__(
        self,
        patient_id: str,
        clinic_id: str,
        assigned_agent: str,
        publisher,
        compression_ratio: float = _DEFAULT_COMPRESSION,
    ) -> None:
        self.patient_id = patient_id
        self.clinic_id = clinic_id
        self.assigned_agent = assigned_agent
        self._publisher = publisher
        self._compression_ratio = compression_ratio
        self._state = "idle"
        self._task_id: str | None = None
        self._alert_id: str | None = None
        self._signals: list[dict] = []

    async def process_signal(self, signal: dict) -> None:
        """Handle a signal event — publish it and trigger the alert + coordination loop."""
        self._signals.append(signal)
        signal_id = str(uuid.uuid4())

        # 1. Publish signal event
        await self._publisher.publish(
            "ocean.signals",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "signal.received",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "source_system": "sim-driver",
                "entity_type": "signal",
                "entity_id": signal_id,
                "payload": {
                    "signal_id": signal_id,
                    "patient_id": self.patient_id,
                    "clinic_id": self.clinic_id,
                    "signal_type": signal.get("type", "unknown"),
                    "value": signal.get("value"),
                    "unit": signal.get("unit", ""),
                    "anomalous": signal.get("anomalous", False),
                },
            },
        )
        self._state = "signal_published"
        log.info("signal_published", patient_id=self.patient_id, signal_type=signal.get("type"))

        if signal.get("anomalous"):
            await self._create_alert(signal)

    async def _create_alert(self, signal: dict) -> None:
        """Publish alert.created event and drive the full coordination loop."""
        alert_id = str(uuid.uuid4())
        self._alert_id = alert_id
        severity = self._infer_severity(signal)

        await self._publisher.publish(
            "ocean.alerts",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "alert.created",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "source_system": "sim-driver",
                "entity_type": "alert",
                "entity_id": alert_id,
                "payload": {
                    "alert_id": alert_id,
                    "patient_id": self.patient_id,
                    "clinic_id": self.clinic_id,
                    "alert_type": f"{signal.get('type', 'unknown')}_anomaly",
                    "severity": severity,
                },
            },
        )
        self._state = "alerted"
        log.info("alert_created", patient_id=self.patient_id, alert_id=alert_id, severity=severity)

        # Simulate task creation (control-plane would create this from the alert)
        task_id = str(uuid.uuid4())
        self._task_id = task_id
        await self._publisher.publish(
            "ocean.tasks",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "task.created",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "source_system": "sim-driver",
                "entity_type": "task",
                "entity_id": task_id,
                "payload": {
                    "task_id": task_id,
                    "alert_id": alert_id,
                    "patient_id": self.patient_id,
                    "task_type": "outreach",
                    "priority": severity.lower(),
                    "alert_type": f"{signal.get('type', 'unknown')}_anomaly",
                    "severity": severity,
                },
            },
        )
        self._state = "task_open"
        log.info("task_created", task_id=task_id, patient_id=self.patient_id)

        await self._claim_task(task_id, alert_id, severity, signal)

    async def _claim_task(
        self,
        task_id: str,
        alert_id: str,
        severity: str,
        signal: dict,
    ) -> None:
        """Wait for agent claim delay, then simulate claim and outreach approval."""
        agent = get_agent(self.assigned_agent)
        delay_secs = claim_delay_seconds(self.assigned_agent)
        # claim_delay_seconds is already a wall-clock duration
        await asyncio.sleep(delay_secs)

        await self._publisher.publish(
            "ocean.tasks",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "task.claimed",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "source_system": "sim-driver",
                "entity_type": "task",
                "entity_id": task_id,
                "payload": {
                    "task_id": task_id,
                    "actor_id": self.assigned_agent,
                },
            },
        )
        self._state = "task_claimed"
        log.info("task_claimed", task_id=task_id, agent=self.assigned_agent)

        await self._run_outreach(task_id, alert_id, severity, signal, agent)

    async def _run_outreach(
        self,
        task_id: str,
        alert_id: str,
        severity: str,
        signal: dict,
        agent: dict,
    ) -> None:
        """Generate outreach draft, judge it, approve/reject."""
        alert_type = f"{signal.get('type', 'unknown')}_anomaly"
        draft_id = str(uuid.uuid4())

        decision = await generate_outreach_decision(
            agent_id=self.assigned_agent,
            alert_type=alert_type,
            severity=severity,
            signals=self._signals,
        )

        # Publish ai.response.drafted
        await self._publisher.publish(
            "ocean.ai-ops",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "ai.response.drafted",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "source_system": "sim-driver",
                "entity_type": "task",
                "entity_id": task_id,
                "payload": {
                    "draft_id": draft_id,
                    "task_id": task_id,
                    "patient_id": self.patient_id,
                    "reasoning": decision.get("reasoning", ""),
                },
            },
        )
        self._state = "outreach_pending"

        # LLM judge scores the decision
        judgment = await judge_action(
            agent_id=self.assigned_agent,
            action=decision["action"],
            alert_type=alert_type,
            severity=severity,
            signals=self._signals,
            proposed_response=decision.get("reasoning", ""),
        )

        if judgment["needs_human"]:
            await post_human_gate(
                patient_id=self.patient_id,
                agent_id=self.assigned_agent,
                action=decision["action"],
                alert_type=alert_type,
                severity=severity,
                score=judgment["score"],
                reasoning=judgment["reasoning"],
                draft_id=draft_id,
            )
            log.info(
                "human_gate_triggered",
                draft_id=draft_id,
                score=judgment["score"],
            )

        action = decision["action"]
        event_type = "ai.output.approved" if action == "approve" else "ai.output.rejected"

        await self._publisher.publish(
            "ocean.ai-ops",
            {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "source_system": "sim-driver",
                "entity_type": "task",
                "entity_id": task_id,
                "payload": {
                    "draft_id": draft_id,
                    "task_id": task_id,
                    "actor_id": self.assigned_agent,
                    "judge_score": judgment["score"],
                },
            },
        )

        self._state = "dispatched" if action == "approve" else "rejected"
        log.info(
            "outreach_outcome",
            task_id=task_id,
            action=action,
            judge_score=judgment["score"],
            patient_id=self.patient_id,
        )

    def _infer_severity(self, signal: dict) -> str:
        """Infer alert severity from signal type and value."""
        signal_type = signal.get("type", "")
        value = signal.get("value", 0)

        if signal_type == "glucose":
            if value > 300:
                return "CRITICAL"
            if value > 200:
                return "URGENT"
            return "HIGH"
        elif signal_type == "spo2":
            if value < 85:
                return "CRITICAL"
            if value < 90:
                return "URGENT"
            return "HIGH"
        return "HIGH"
