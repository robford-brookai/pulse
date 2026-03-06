"""Routing rules for the control-plane alert dispatcher.

Each RoutingRule maps an alert_type to a Slack channel and priority level.
channel_for() and priority_for() provide lookup with safe fallbacks.
"""
from __future__ import annotations

from dataclasses import dataclass

FALLBACK_CHANNEL = "#care-alerts-general"
FALLBACK_PRIORITY = "routine"


@dataclass(frozen=True)
class RoutingRule:
    alert_type: str
    channel: str
    priority: str


ROUTING_RULES: list[RoutingRule] = [
    RoutingRule(alert_type="glucose", channel="#care-alerts-glucose", priority="urgent"),
    RoutingRule(alert_type="blood_pressure", channel="#care-alerts-bp", priority="urgent"),
    RoutingRule(alert_type="heart_rate", channel="#care-alerts-hr", priority="routine"),
    RoutingRule(alert_type="weight", channel="#care-alerts-weight", priority="routine"),
    RoutingRule(alert_type="medication", channel="#care-alerts-medication", priority="routine"),
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
