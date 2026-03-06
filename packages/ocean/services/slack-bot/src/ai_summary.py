# AUDIT-04 GATE: Anthropic HIPAA BAA must be confirmed before deploying to production.
# Context sent to Claude: alert_type, severity, patient_id hash, timestamp ONLY.
# No PHI (name, DOB, MRN, clinic) is included in the prompt — HIPAA-safe by design.
# Production deploy is blocked until BAA is confirmed.
"""AI-powered alert summary generation."""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

log = structlog.get_logger()

_client = AsyncAnthropic()


async def generate_summary(
    alert_type: str,
    severity: str,
    patient_hash: str,
    timestamp: str,
) -> str:
    """Generate a clinical context summary for an alert using Anthropic.

    Sends only non-PHI fields (alert_type, severity, patient_hash, timestamp).
    Returns "AI summary unavailable." on any exception — fail-open, never re-raises.
    """
    try:
        prompt = (
            f"Generate a 1-2 sentence clinical summary for a care coordinator reviewing a "
            f"{severity} {alert_type} alert at {timestamp}. "
            f"Patient reference: {patient_hash}. "
            f"Be concise and action-oriented. Do not include any PHI."
        )
        response = await _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        log.warning("ai_summary_failed", alert_type=alert_type)
        return "AI summary unavailable."
