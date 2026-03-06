"""LLM-as-judge: scores agent actions for realism and clinical appropriateness.

Uses Claude Haiku for speed and cost. Returns a structured score dict.
When confidence < 0.7 or action is 'approve' on CRITICAL alert, sets needs_human=True
so the human gate can intervene.
"""
from __future__ import annotations

import json
import re

import structlog
from anthropic import AsyncAnthropic

log = structlog.get_logger()

_client = AsyncAnthropic()

_JUDGE_SYSTEM = (
    "You are a clinical quality reviewer evaluating care coordinator decisions. "
    "Score the decision from 0.0 (clearly wrong) to 1.0 (clearly appropriate). "
    "Return a JSON object: {\"score\": float, \"reasoning\": str}. "
    "No other text — only valid JSON."
)


async def judge_action(
    agent_id: str,
    action: str,
    alert_type: str,
    severity: str,
    signals: list[dict],
    proposed_response: str,
) -> dict:
    """Score an agent action for clinical realism.

    Returns:
        {score: float[0,1], reasoning: str, needs_human: bool}

    needs_human is True when:
        - score < 0.7
        - action == 'approve' AND severity == 'CRITICAL'
    """
    signal_lines = "\n".join(
        f"  - {s.get('signal_type')}: {s.get('value')} {s.get('unit')}"
        + (" [ANOMALOUS]" if s.get("anomalous") else "")
        for s in signals[:5]
    ) or "  (none)"

    prompt = (
        f"Agent: {agent_id}\n"
        f"Alert: {severity} {alert_type}\n"
        f"Signals:\n{signal_lines}\n"
        f"Decision: {action}\n"
        f"Response: {proposed_response}\n\n"
        "Is this decision clinically appropriate? Return JSON only."
    )

    try:
        response = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Extract JSON from response (handle markdown fences)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = {"score": 0.5, "reasoning": text}

        score = float(data.get("score", 0.5))
        reasoning = str(data.get("reasoning", ""))

    except Exception:
        log.warning("llm_judge_failed", agent_id=agent_id, action=action)
        score = 0.5
        reasoning = "Judge unavailable — default score 0.5."

    needs_human = score < 0.7 or (action == "approve" and severity == "CRITICAL")

    return {"score": score, "reasoning": reasoning, "needs_human": needs_human}
