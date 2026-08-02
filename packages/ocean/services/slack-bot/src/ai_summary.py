# AUDIT-04 GATE: Anthropic HIPAA BAA must be confirmed before deploying to production.
# Context sent to Claude: alert_type, severity, patient_id hash, timestamp, and
# WHITELISTED graph signals ONLY — no free-text clinical notes, no PHI identifiers.
# Production deploy is blocked until BAA is confirmed.
#
# PHI whitelist: Only signal_type (categorical), value (numeric), unit (categorical),
# anomalous (bool) enter the prompt — no free-text fields from the clinical record.
"""AI-powered alert summary generation with Hasura graph context."""

from __future__ import annotations

import httpx
import structlog
from anthropic import AsyncAnthropic

log = structlog.get_logger()

_client = AsyncAnthropic()

# GraphQL query for patient context: signals + alerts in a 48h window.
# Fields are whitelisted — only categorical/numeric, no free-text.
CONTEXT_QUERY = """
query PatientContext($patient_id: String!, $since: timestamptz!) {
  signals(
    where: {patient_id: {_eq: $patient_id}, received_at: {_gte: $since}}
    order_by: {received_at: desc}
    limit: 10
  ) {
    signal_type
    value
    unit
    anomalous
    received_at
  }
  alerts(
    where: {patient_id: {_eq: $patient_id}, created_at: {_gte: $since}}
    order_by: {created_at: desc}
    limit: 5
  ) {
    alert_type
    severity
    status
    created_at
  }
}
"""


async def fetch_patient_context(
    patient_id: str,
    hasura_url: str,
    hasura_secret: str,
) -> dict:
    """Fetch recent signals and alerts for a patient from the Hasura graph.

    Returns the data dict on success. On any exception, logs a warning and
    returns {} — degraded AI (no context) is always preferred over hard failure.
    """
    from datetime import UTC, datetime, timedelta

    since = (datetime.now(UTC) - timedelta(hours=48)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{hasura_url}/v1/graphql",
                headers={"x-hasura-admin-secret": hasura_secret},
                json={
                    "query": CONTEXT_QUERY,
                    "variables": {"patient_id": patient_id, "since": since},
                },
            )
            response.raise_for_status()
            return response.json()
    except Exception:
        log.warning(
            "fetch_patient_context_failed",
            patient_hash=patient_id[:8] + "...",
            hasura_url=hasura_url,
        )
        return {}


async def generate_summary_with_context(
    alert_type: str,
    severity: str,
    patient_hash: str,
    timestamp: str,
    hasura_url: str,
    hasura_secret: str,
) -> tuple[str, list[str]]:
    """Generate a clinical context summary using graph-grounded signals.

    Returns (summary_text, cited_signal_types). On any exception returns a
    safe degraded response — never re-raises.

    PHI safety: patient_hash is an opaque hash. Only whitelisted signal fields
    (signal_type, value, unit, anomalous) enter the prompt.
    """
    try:
        context = await fetch_patient_context(patient_hash, hasura_url, hasura_secret)

        signals: list[dict] = []
        if context:
            data = context.get("data", {})
            signals = data.get("signals", []) if data else []

        # Cited signals: up to 5 signal types from context
        cited_signal_types = [s["signal_type"] for s in signals[:5]]

        # Build prompt with whitelisted fields only
        signal_summary = ""
        if signals:
            signal_lines = []
            for s in signals[:5]:
                anomalous_flag = " [ANOMALOUS]" if s.get("anomalous") else ""
                signal_lines.append(f"  - {s['signal_type']}: {s['value']} {s['unit']}{anomalous_flag}")
            signal_summary = "\nRecent signals:\n" + "\n".join(signal_lines)

        prompt = (
            f"Generate a 1-2 sentence clinical summary for a care coordinator reviewing a "
            f"{severity} {alert_type} alert at {timestamp}. "
            f"Patient reference: {patient_hash}.{signal_summary} "
            f"Be concise and action-oriented. Do not include any PHI."
        )

        response = await _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text, cited_signal_types

    except Exception:
        log.warning("ai_summary_failed", alert_type=alert_type)
        return "AI summary unavailable.", []
