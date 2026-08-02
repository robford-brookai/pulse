"""Deterministic severity-based fallback for when Anthropic API is unavailable."""

from __future__ import annotations

import structlog

log = structlog.get_logger()

# Signal types that warrant automatic approval at URGENT severity.
_URGENT_APPROVE_SIGNALS = {"glucose", "spo2"}


def deterministic_fallback(alert_context: dict) -> tuple[str, float]:
    """Apply rule-based decision when Haiku API is unavailable.

    Rules:
      CRITICAL -> approve (1.0)
      URGENT + glucose/spo2 -> approve (0.8)
      URGENT + other -> escalate (0.5)
      HIGH or lower -> escalate (0.3)
    """
    severity = (alert_context.get("severity", "") or alert_context.get("priority", "")).upper()

    signal_type = (alert_context.get("signal_type", "") or alert_context.get("task_type", "")).lower()

    if severity == "CRITICAL":
        return ("approve", 1.0)

    if severity == "URGENT":
        if signal_type in _URGENT_APPROVE_SIGNALS:
            return ("approve", 0.8)
        return ("escalate", 0.5)

    # HIGH and everything else
    return ("escalate", 0.3)
