"""Persona model and AGENTS.md YAML loader."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class Persona(BaseModel):
    """Immutable persona definition loaded from AGENTS.md."""

    model_config = {"frozen": True}

    id: str
    role: str
    slack_name: str | None = None
    claim_delay_seconds: tuple[int, int] | None = None
    outreach_approve_rate: float | None = None
    escalation_triggers: list[str] = []
    call_answer_rate: float | None = None
    missed_call_retry_count: int | None = None
    retry_delay_seconds: int | None = None
    human_escalation_responder: bool = False
    monitors_channel: str | None = None
    system_prompt: str | None = None

    @field_validator("claim_delay_seconds", mode="before")
    @classmethod
    def _coerce_delay_tuple(cls, v: object) -> tuple[int, int] | None:
        if v is None:
            return None
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return (int(v[0]), int(v[1]))
        return v  # type: ignore[return-value]


_YAML_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)


def load_personas(agents_md_path: str) -> list[Persona]:
    """Parse AGENTS.md, extract fenced YAML block, return list of Persona."""
    text = Path(agents_md_path).read_text()
    match = _YAML_FENCE_RE.search(text)
    if match is None:
        raise ValueError(f"No YAML block found in {agents_md_path}")

    data = yaml.safe_load(match.group(1))
    raw_personas = data.get("personas", [])
    if not raw_personas:
        raise ValueError(f"No personas found in YAML block of {agents_md_path}")

    return [Persona(**p) for p in raw_personas]
