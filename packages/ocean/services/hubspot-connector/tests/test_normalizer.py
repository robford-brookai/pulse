"""Tests for HubSpot event normalization and PHI safety."""
from __future__ import annotations


def _make_raw(*, sub_type: str = "contact.creation", object_id: int = 12345, **kwargs) -> dict:
    event = {
        "subscriptionType": sub_type,
        "objectId": object_id,
        "changeSource": "CRM",
    }
    event.update(kwargs)
    return event


class TestSubscriptionTypeMapping:
    def test_contact_creation(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(sub_type="contact.creation"))
        assert event is not None
        assert event["event_type"] == "contact.created"
        assert event["entity_type"] == "contact"
        assert event["entity_id"] == "12345"
        assert event["source_system"] == "hubspot"

    def test_contact_deletion(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(sub_type="contact.deletion"))
        assert event is not None
        assert event["event_type"] == "contact.deleted"

    def test_contact_property_change(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(
            sub_type="contact.propertyChange",
            propertyName="lifecyclestage",
            propertyValue="customer",
        ))
        assert event is not None
        assert event["event_type"] == "contact.updated"
        assert event["payload"]["property_name"] == "lifecyclestage"
        assert event["payload"]["property_value"] == "customer"

    def test_unsupported_type_returns_none(self):
        from src.normalizer import normalize_event

        assert normalize_event(_make_raw(sub_type="deal.creation")) is None


class TestPHIRedaction:
    def test_phi_field_redacted(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(
            sub_type="contact.propertyChange",
            propertyName="email",
            propertyValue="patient@example.com",
        ))
        assert event is not None
        assert event["payload"]["property_value"] == "[REDACTED]"
        assert event["payload"]["property_name"] == "email"

    def test_camelcase_phi_redacted(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(
            sub_type="contact.propertyChange",
            propertyName="firstName",
            propertyValue="Jane",
        ))
        assert event is not None
        assert event["payload"]["property_value"] == "[REDACTED]"

    def test_unknown_field_filtered(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(
            sub_type="contact.propertyChange",
            propertyName="custom_field_xyz",
            propertyValue="some value",
        ))
        assert event is not None
        assert event["payload"]["property_value"] == "[FILTERED]"

    def test_safe_field_passes(self):
        from src.normalizer import normalize_event

        event = normalize_event(_make_raw(
            sub_type="contact.propertyChange",
            propertyName="hs_lead_status",
            propertyValue="OPEN",
        ))
        assert event is not None
        assert event["payload"]["property_value"] == "OPEN"


class TestEdgeCases:
    def test_missing_object_id_returns_none(self):
        from src.normalizer import normalize_event

        raw = {"subscriptionType": "contact.creation"}
        assert normalize_event(raw) is None
