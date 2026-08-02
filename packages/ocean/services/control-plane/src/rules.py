"""Routing rules for the control-plane alert and ticket dispatcher.

Each RoutingRule maps an alert_type to a Slack channel and priority level.
channel_for() and priority_for() provide lookup with safe fallbacks.

Ticket routing uses category-to-channel and priority-to-crosspost mappings.
State transitions are validated against VALID_TRANSITIONS.
"""
from __future__ import annotations

from dataclasses import dataclass

FALLBACK_CHANNEL = "#care-alerts-general"
FALLBACK_PRIORITY = "medium"


@dataclass(frozen=True)
class RoutingRule:
    alert_type: str
    channel: str
    priority: str


ROUTING_RULES: list[RoutingRule] = [
    RoutingRule(alert_type="glucose", channel="#care-alerts-glucose", priority="critical"),
    RoutingRule(alert_type="blood_pressure", channel="#care-alerts-bp", priority="critical"),
    RoutingRule(alert_type="heart_rate", channel="#care-alerts-hr", priority="medium"),
    RoutingRule(alert_type="weight", channel="#care-alerts-weight", priority="medium"),
    RoutingRule(alert_type="medication", channel="#care-alerts-medication", priority="medium"),
]

_RULES_BY_TYPE: dict[str, RoutingRule] = {r.alert_type: r for r in ROUTING_RULES}


def channel_for(alert_type: str) -> str:
    """Return the Slack channel for the given alert_type, or FALLBACK_CHANNEL."""
    rule = _RULES_BY_TYPE.get(alert_type)
    return rule.channel if rule is not None else FALLBACK_CHANNEL


def priority_for(alert_type: str) -> str:
    """Return the priority for the given alert_type, or FALLBACK_PRIORITY."""
    rule = _RULES_BY_TYPE.get(alert_type)
    return rule.priority if rule is not None else FALLBACK_PRIORITY


# ---------------------------------------------------------------------------
# Ticket routing
# ---------------------------------------------------------------------------

TICKET_CATEGORY_CHANNELS: dict[str, str] = {
    "device_issue": "#ocean-devices",
    "patient_activation": "#ocean-activation",
    "clinical_support": "#ocean-clinical",
    "engineering_it": "#ocean-engineering",
}

TICKET_PRIORITY_CHANNELS: dict[str, list[str]] = {
    "critical": ["#ocean-critical"],
    "high": ["#ocean-high"],
    "medium": [],
    "low": [],
}

FALLBACK_TICKET_CHANNEL = "#ocean-devices"


def ticket_channel_for(category: str) -> str:
    """Return the primary Slack channel for a ticket category."""
    return TICKET_CATEGORY_CHANNELS.get(category, FALLBACK_TICKET_CHANNEL)


def ticket_priority_channels(priority: str) -> list[str]:
    """Return cross-post channels for the given ticket priority."""
    return TICKET_PRIORITY_CHANNELS.get(priority, [])


# ---------------------------------------------------------------------------
# Ticket state machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "waiting"},
    "in_progress": {"waiting", "resolved"},
    "waiting": {"in_progress", "resolved"},
}


def is_valid_transition(current: str, target: str) -> bool:
    """Return True if transitioning from current to target status is allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    return target in allowed


# ---------------------------------------------------------------------------
# Delivery notification routing
# ---------------------------------------------------------------------------

DELIVERY_NOTIFICATION_CHANNEL = "#ocean-activation"


# ---------------------------------------------------------------------------
# Escalation policy
# ---------------------------------------------------------------------------

PRIORITY_UPGRADE: dict[str, str] = {
    "low": "medium",
    "medium": "high",
    "high": "critical",
    # critical stays critical — posts UNCLAIMED CRITICAL warning instead
}


def delivery_channel_for() -> str:
    """Return the Slack channel for delivery handoff notifications.

    Activation channel is the natural home for delivery handoffs since
    they trigger patient onboarding.
    """
    return DELIVERY_NOTIFICATION_CHANNEL
