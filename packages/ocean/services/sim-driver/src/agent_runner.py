"""Claude Haiku-powered agent persona executor.

Loads agent personas from agents.md (repo root). Each agent has a system_prompt,
claim_delay range, and approval rate. The runner uses Claude Haiku to generate
realistic coordinator decisions given the current situation.
"""
from __future__ import annotations

import pathlib
import re
import random
from typing import Any

import structlog
import yaml
from anthropic import AsyncAnthropic

log = structlog.get_logger()

_client = AsyncAnthropic()
_AGENTS_MD = pathlib.Path(__file__).parents[4] / "agents.md"

# Cached agents config (loaded once)
_agents_cache: dict[str, dict] | None = None


def _load_agents() -> dict[str, dict]:
    """Parse YAML from the first ```yaml block in agents.md."""
    global _agents_cache
    if _agents_cache is not None:
        return _agents_cache

    try:
        text = _AGENTS_MD.read_text()
        match = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
        if not match:
            log.warning("agents_md_no_yaml_block", path=str(_AGENTS_MD))
            return {}
        data = yaml.safe_load(match.group(1))
        agents = {a["id"]: a for a in data.get("agents", [])}
        _agents_cache = agents
        log.info("agents_loaded", count=len(agents))
        return agents
    except Exception:
        log.warning("agents_load_failed", path=str(_AGENTS_MD))
        return {}


def get_agent(agent_id: str) -> dict:
    """Return agent config by id, or a default config if not found."""
    agents = _load_agents()
    return agents.get(agent_id, {
        "id": agent_id,
        "claim_delay_seconds": [30, 120],
        "outreach_approve_rate": 0.75,
        "escalation_triggers": ["CRITICAL"],
        "system_prompt": "You are a care coordinator reviewing patient alerts.",
    })


def claim_delay_seconds(agent_id: str) -> float:
    """Return a random claim delay within the agent's configured range."""
    agent = get_agent(agent_id)
    lo, hi = agent.get("claim_delay_seconds", [30, 120])
    return random.uniform(lo, hi)


async def generate_outreach_decision(
    agent_id: str,
    alert_type: str,
    severity: str,
    signals: list[dict],
) -> dict[str, Any]:
    """Use Claude Haiku to generate an approve/reject decision for outreach.

    Returns {'action': 'approve'|'reject', 'reasoning': str}.
    Falls back to a deterministic decision based on outreach_approve_rate on failure.
    """
    agent = get_agent(agent_id)

    # Deterministic fallback using approve rate
    if random.random() > agent.get("outreach_approve_rate", 0.75):
        return {"action": "reject", "reasoning": "Agent escalated based on uncertainty."}

    signal_lines = "\n".join(
        f"  - {s.get('signal_type')}: {s.get('value')} {s.get('unit')}"
        + (" [ANOMALOUS]" if s.get("anomalous") else "")
        for s in signals[:5]
    )

    prompt = (
        f"You are a care coordinator. A patient has a {severity} {alert_type} alert.\n"
        f"Recent signals:\n{signal_lines}\n\n"
        f"Should you approve outreach? Reply with exactly one word: APPROVE or REJECT, "
        f"then a brief one-sentence reason."
    )

    try:
        response = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=agent.get("system_prompt", ""),
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        action = "approve" if text.upper().startswith("APPROVE") else "reject"
        return {"action": action, "reasoning": text}
    except Exception:
        log.warning("agent_decision_failed", agent_id=agent_id)
        return {"action": "approve", "reasoning": "Default approve (LLM unavailable)."}
