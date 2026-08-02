"""Mock POCAR webhook payload contract.

PLACEHOLDER — validate with Brook engineering before production cutover.
Fields are inferred from standard RPM care alert patterns.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class POCARWebhookPayload(BaseModel):
    alert_id: str
    patient_id: str
    alert_type: str
    severity: str
    clinic_id: str
    triggered_at: datetime
    signal_type: str | None = None
    signal_value: float | None = None
