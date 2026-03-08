"""Tests for persona loading from AGENTS.md."""
from __future__ import annotations

import os
import textwrap

import pytest

from src.personas import Persona, load_personas


AGENTS_MD = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, "agents.md"
)


class TestPersonaModel:
    def test_persona_fields(self):
        p = Persona(
            id="coordinator_alice",
            role="Senior Care Coordinator",
            claim_delay_seconds=(15, 90),
            outreach_approve_rate=0.85,
            call_answer_rate=0.80,
            missed_call_retry_count=1,
            retry_delay_seconds=120,
            escalation_triggers=["CRITICAL"],
        )
        assert p.id == "coordinator_alice"
        assert p.claim_delay_seconds == (15, 90)
        assert p.human_escalation_responder is False

    def test_persona_defaults(self):
        p = Persona(id="test", role="Test")
        assert p.human_escalation_responder is False
        assert p.outreach_approve_rate is None
        assert p.call_answer_rate is None
        assert p.missed_call_retry_count is None
        assert p.retry_delay_seconds is None
        assert p.escalation_triggers == []
        assert p.claim_delay_seconds is None

    def test_persona_frozen(self):
        p = Persona(id="test", role="Test")
        with pytest.raises(Exception):
            p.id = "changed"

    def test_carol_null_fields(self):
        p = Persona(
            id="ops_lead_carol",
            role="Operations Lead",
            human_escalation_responder=True,
            call_answer_rate=None,
            missed_call_retry_count=None,
            retry_delay_seconds=None,
        )
        assert p.human_escalation_responder is True
        assert p.call_answer_rate is None


class TestLoadPersonas:
    def test_load_from_agents_md(self):
        personas = load_personas(AGENTS_MD)
        assert len(personas) == 3
        ids = [p.id for p in personas]
        assert "coordinator_alice" in ids
        assert "coordinator_bob" in ids
        assert "ops_lead_carol" in ids

    def test_alice_values(self):
        personas = load_personas(AGENTS_MD)
        alice = next(p for p in personas if p.id == "coordinator_alice")
        assert alice.claim_delay_seconds == (15, 90)
        assert alice.outreach_approve_rate == 0.85
        assert alice.call_answer_rate == 0.80
        assert alice.missed_call_retry_count == 1
        assert alice.retry_delay_seconds == 120
        assert alice.human_escalation_responder is False

    def test_bob_values(self):
        personas = load_personas(AGENTS_MD)
        bob = next(p for p in personas if p.id == "coordinator_bob")
        assert bob.claim_delay_seconds == (60, 300)
        assert bob.outreach_approve_rate == 0.60
        assert bob.call_answer_rate == 0.60
        assert bob.missed_call_retry_count == 0

    def test_carol_is_escalation_responder(self):
        personas = load_personas(AGENTS_MD)
        carol = next(p for p in personas if p.id == "ops_lead_carol")
        assert carol.human_escalation_responder is True
        assert carol.call_answer_rate is None

    def test_raises_on_no_yaml(self, tmp_path):
        md = tmp_path / "empty.md"
        md.write_text("# No yaml block here\n")
        with pytest.raises(ValueError, match="No YAML"):
            load_personas(str(md))

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_personas(str(tmp_path / "nonexistent.md"))


class TestExtendedTypes:
    def test_source_system_includes_new_values(self):
        from ocean_events.types import SourceSystem
        from typing import get_args

        args = get_args(SourceSystem)
        assert "control-plane" in args
        assert "agent-worker" in args
        assert "call-simulator" in args
        assert "sim-driver" in args

    def test_event_type_includes_new_values(self):
        from ocean_events.types import EventType
        from typing import get_args

        args = get_args(EventType)
        assert "ai.recommendation.generated" in args
        assert "ai.output.rejected" in args
