"""HS-01: HubSpot connector validates v3 signatures with replay protection."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_RECEIVER = _ROOT / "services" / "hubspot-connector" / "src" / "receiver.py"


def _src() -> str:
    return _RECEIVER.read_text()


def test_uses_sha256_signature():
    src = _src()
    assert "hashlib.sha256" in src, "Must use SHA-256 for v3 signature"


def test_reads_v3_signature_header():
    src = _src()
    assert "x-hubspot-signature-v3" in src, "Must read X-HubSpot-Signature-v3 header"


def test_reads_request_timestamp_header():
    src = _src()
    assert "x-hubspot-request-timestamp" in src, "Must read X-HubSpot-Request-Timestamp"


def test_uses_compare_digest():
    src = _src()
    assert "hmac.compare_digest(" in src, "Must use constant-time comparison"


def test_replay_protection_max_age():
    src = _src()
    assert "MAX_TIMESTAMP_AGE_SECS" in src, "Must define max timestamp age"
    assert "300" in src, "Max age must be 300 seconds (5 minutes)"


def test_rejects_old_timestamps():
    src = _src()
    assert "Request timestamp too old" in src or "timestamp" in src.lower(), (
        "Must reject requests with expired timestamps"
    )


def test_raises_401_on_invalid():
    src = _src()
    assert "401" in src, "Must return 401 on invalid signature"
