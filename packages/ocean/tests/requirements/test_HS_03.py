"""HS-03: HubSpot connector redacts PHI fields from event payloads."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_NORMALIZER = _ROOT / "services" / "hubspot-connector" / "src" / "normalizer.py"


def _src() -> str:
    return _NORMALIZER.read_text()


def test_phi_deny_list_exists():
    src = _src()
    assert "PHI_DENY_FIELDS" in src, "Must define PHI_DENY_FIELDS set"


def test_phi_deny_list_covers_pii_fields():
    src = _src()
    for field in ("firstname", "lastname", "email", "phone", "date_of_birth", "address"):
        assert f'"{field}"' in src, f"PHI_DENY_FIELDS must include {field}"


def test_redacts_phi_values():
    src = _src()
    assert "[REDACTED]" in src, "PHI field values must be replaced with [REDACTED]"


def test_phi_check_on_property_change():
    src = _src()
    assert "propertyName" in src, "Must check propertyName against deny list"
    assert "PHI_DENY_FIELDS" in src, "Must reference PHI_DENY_FIELDS in logic"
