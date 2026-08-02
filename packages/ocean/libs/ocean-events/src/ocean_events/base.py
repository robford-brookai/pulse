"""BaseEvent with PHI guard for all Ocean events."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, model_validator

_PHI_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "patient_name",
        "first_name",
        "last_name",
        "full_name",
        "date_of_birth",
        "dob",
        "birth_date",
        "mrn",
        "medical_record_number",
        "ssn",
        "social_security_number",
        "address",
        "street_address",
        "zip_code",
        "postal_code",
        "phone",
        "phone_number",
        "cell_phone",
        "home_phone",
        "email",
        "email_address",
        "diagnosis",
        "diagnosis_code",
        "icd_code",
        "medication",
        "prescription",
        "clinical_note",
        "chart_note",
        "glucose_value",
        "blood_pressure",
        "weight_kg",
        "bmi",
    }
)


class BaseEvent(BaseModel):
    """
    Root event type. All Ocean events must subclass this.

    PHI field names raise TypeError at class definition time (import time).
    PHI keys in the payload dict raise ValueError at instance creation time.
    Events are immutable after construction (frozen model).
    """

    event_id: UUID
    event_type: str  # "alert.created" — past-tense, dot-namespaced
    schema_version: str  # "1.0.0"
    timestamp: datetime  # UTC ISO 8601
    source_system: str  # "pocar" | "zcc" | "ocean" | "linear"
    entity_type: str  # "alert" | "patient" | "task" | "interaction" | "outcome"
    entity_id: str  # opaque ID, no PHI
    correlation_id: str  # workflow trace ID
    actor_id: str | None  # user ID or system name
    payload: dict  # event-specific metadata, NO PHI

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Check own class annotations only (model_fields is not fully populated at this point
        # in Pydantic v2 — it only contains inherited fields, not the subclass's own new fields).
        own_annotations = cls.__dict__.get("__annotations__", {})
        for field_name in own_annotations:
            if field_name.lower() in _PHI_FIELD_NAMES:
                raise TypeError(
                    f"Event class '{cls.__name__}' contains PHI field '{field_name}'. "
                    f"Events must not carry PHI. Use an opaque identifier and fetch "
                    f"clinical detail from the PHI-bearing system by ID."
                )

    @model_validator(mode="after")
    def _check_payload_phi(self) -> BaseEvent:
        phi_keys = _PHI_FIELD_NAMES.intersection(self.payload.keys())
        if phi_keys:
            raise ValueError(
                f"Event payload contains PHI key(s): {sorted(phi_keys)}. "
                f"PHI must not be included in event payloads."
            )
        return self

    model_config = {"frozen": True}
