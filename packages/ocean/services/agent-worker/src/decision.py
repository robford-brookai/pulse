# AUDIT-04 GATE: Anthropic HIPAA BAA must be confirmed before deploying to production.
# Context sent to Claude: signal_type (categorical), value (numeric), severity (categorical),
# anomalous (bool) ONLY -- no free-text clinical notes, no PHI identifiers.
# Production deploy is blocked until BAA is confirmed.
"""AI decision pipeline: Haiku outreach decision + judge scoring."""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic

from src.fallback import deterministic_fallback

log = structlog.get_logger()

_client = AsyncAnthropic()


def _build_decision_prompt(alert_context: dict) -> str:
    """Build PHI-safe prompt from whitelisted fields only."""
    return (
        "You are a clinical decision support system. Based on the following alert data, "
        "decide whether to approve outreach to the patient or escalate to a supervisor.\n\n"
        f"Signal type: {alert_context.get('signal_type', 'unknown')}\n"
        f"Severity: {alert_context.get('severity', 'unknown')}\n"
        f"Value: {alert_context.get('value', 'N/A')}\n"
        f"Anomalous: {alert_context.get('anomalous', 'unknown')}\n\n"
        'Respond with JSON only: {"action": "approve" or "escalate", "reasoning": "<brief reasoning>"}'
    )


def _build_judge_prompt(decision: dict, alert_context: dict) -> str:
    """Build prompt for judge to score decision confidence."""
    return (
        "You are a clinical decision quality judge. Rate the following outreach decision "
        "on a confidence scale from 0.0 to 1.0.\n\n"
        f"Alert severity: {alert_context.get('severity', 'unknown')}\n"
        f"Signal type: {alert_context.get('signal_type', 'unknown')}\n"
        f"Decision: {decision.get('action', 'unknown')}\n"
        f"Reasoning: {decision.get('reasoning', 'none')}\n\n"
        'Respond with JSON only: {"confidence": <float 0.0-1.0>}'
    )


async def generate_outreach_decision(alert_context: dict) -> dict:
    """Call Haiku to generate an outreach decision.

    Returns dict with 'action' and 'reasoning' keys.
    """
    prompt = _build_decision_prompt(alert_context)
    response = await _client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    return json.loads(text)


async def judge_decision(decision: dict, alert_context: dict) -> float:
    """Call Haiku to judge decision confidence. Returns float 0-1."""
    prompt = _build_judge_prompt(decision, alert_context)
    response = await _client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    parsed = json.loads(text)
    confidence = float(parsed["confidence"])
    return max(0.0, min(1.0, confidence))


async def decide_with_fallback(alert_context: dict) -> tuple[str, float]:
    """Run Haiku decision + judge pipeline, fall back to deterministic rules on error."""
    try:
        decision = await generate_outreach_decision(alert_context)
        confidence = await judge_decision(decision, alert_context)
        action = decision.get("action", "escalate")
        log.info(
            "ai_decision_completed",
            action=action,
            confidence=confidence,
        )
        return (action, confidence)
    except Exception:
        log.warning("ai_decision_fallback", reason="haiku_unavailable")
        return deterministic_fallback(alert_context)
