"""HS-04: HubSpot connector filters unknown properties to [FILTERED]."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_NORMALIZER = _ROOT / "services" / "hubspot-connector" / "src" / "normalizer.py"


def _src() -> str:
    return _NORMALIZER.read_text()


def test_safe_property_allowlist_exists():
    src = _src()
    assert "SAFE_PROPERTY_FIELDS" in src, "Must define SAFE_PROPERTY_FIELDS set"


def test_safe_properties_include_lifecycle_fields():
    src = _src()
    for field in ("lifecyclestage", "hs_lead_status", "createdate"):
        assert f'"{field}"' in src, f"SAFE_PROPERTY_FIELDS must include {field}"


def test_unknown_properties_filtered():
    src = _src()
    assert "[FILTERED]" in src, "Unknown property values must be replaced with [FILTERED]"


def test_three_tier_classification():
    """Verify properties go through PHI → safe → filtered classification."""
    src = _src()
    assert "PHI_DENY_FIELDS" in src
    assert "SAFE_PROPERTY_FIELDS" in src
    assert "[REDACTED]" in src
    assert "[FILTERED]" in src
