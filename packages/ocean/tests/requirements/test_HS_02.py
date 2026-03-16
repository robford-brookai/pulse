"""HS-02: HubSpot connector normalizes contact lifecycle events."""
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_NORMALIZER = _ROOT / "services" / "hubspot-connector" / "src" / "normalizer.py"


def _src() -> str:
    return _NORMALIZER.read_text()


def test_maps_contact_creation():
    src = _src()
    assert '"contact.creation"' in src, "Must handle contact.creation subscription"
    assert '"contact.created"' in src, "Must map to contact.created event type"


def test_maps_contact_deletion():
    src = _src()
    assert '"contact.deletion"' in src, "Must handle contact.deletion subscription"
    assert '"contact.deleted"' in src, "Must map to contact.deleted event type"


def test_maps_contact_property_change():
    src = _src()
    assert '"contact.propertyChange"' in src, "Must handle contact.propertyChange"
    assert '"contact.updated"' in src, "Must map to contact.updated event type"


def test_source_system_is_hubspot():
    src = _src()
    assert '"hubspot"' in src, "source_system must be 'hubspot'"


def test_entity_type_is_contact():
    src = _src()
    assert '"contact"' in src, "entity_type must be 'contact'"


def test_uses_object_id_as_entity_id():
    src = _src()
    assert "objectId" in src, "Must extract objectId from HubSpot payload"
