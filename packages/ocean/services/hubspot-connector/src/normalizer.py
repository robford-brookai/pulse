"""Normalize HubSpot webhook payloads to Ocean event format."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

SUBSCRIPTION_TYPE_MAP: dict[str, str] = {
    "contact.creation": "contact.created",
    "contact.deletion": "contact.deleted",
    "contact.propertyChange": "contact.updated",
}

PHI_DENY_FIELDS: set[str] = {
    "firstname",
    "lastname",
    "email",
    "phone",
    "mobilephone",
    "date_of_birth",
    "address",
    "city",
    "state",
    "zip",
    "country",
    "hs_email_domain",
    "firstName",
    "lastName",
    "dateOfBirth",
    "mobilePhone",
}

SAFE_PROPERTY_FIELDS: set[str] = {
    "lifecyclestage",
    "hs_lead_status",
    "createdate",
    "lastmodifieddate",
    "hs_object_id",
    "associatedcompanyid",
    "hs_analytics_source",
}


def normalize_event(raw: dict) -> dict | None:
    """Map a HubSpot subscription event to an Ocean signal event.

    Returns None for unsupported subscription types.
    """
    sub_type = raw.get("subscriptionType", "")
    event_type = SUBSCRIPTION_TYPE_MAP.get(sub_type)
    if event_type is None:
        return None

    object_id = str(raw.get("objectId", ""))
    if not object_id:
        return None

    payload: dict = {
        "hubspot_contact_id": object_id,
        "subscription_type": sub_type,
        "change_source": raw.get("changeSource", ""),
    }

    if sub_type == "contact.propertyChange":
        prop_name = raw.get("propertyName", "")
        prop_value = raw.get("propertyValue", "")
        if prop_name in PHI_DENY_FIELDS:
            payload["property_name"] = prop_name
            payload["property_value"] = "[REDACTED]"
        elif prop_name in SAFE_PROPERTY_FIELDS:
            payload["property_name"] = prop_name
            payload["property_value"] = prop_value
        else:
            payload["property_name"] = prop_name
            payload["property_value"] = "[FILTERED]"

    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "source_system": "hubspot",
        "entity_type": "contact",
        "entity_id": object_id,
        "correlation_id": str(uuid4()),
        "actor_id": None,
        "payload": payload,
    }
