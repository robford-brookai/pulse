# AUDIT-04 GATE: Anthropic API calls require HIPAA BAA before production use.
# The generate_summary function must NOT be called in production until the BAA is confirmed.
# Any prompt sent to Anthropic must be reviewed for PHI — patient_hash is a pseudonym only.
# Track BAA status: [link to Linear/Notion issue]
"""AI-powered alert summary generation — stub. Implemented in 03-03."""
from __future__ import annotations


async def generate_summary(
    alert_type: str,
    severity: str,
    patient_hash: str,
    timestamp: str,
) -> str:
    """Generate a clinical context summary for an alert using Anthropic.

    Returns a human-readable summary string. Stub — implemented in 03-03.
    """
    return "AI summary unavailable."
