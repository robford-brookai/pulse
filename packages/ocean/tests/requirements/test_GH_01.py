"""GH-01: GitHub connector validates HMAC-SHA256 webhook signatures."""
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_RECEIVER = _ROOT / "services" / "github-connector" / "src" / "receiver.py"


def _src() -> str:
    return _RECEIVER.read_text()


def test_uses_hmac_sha256():
    src = _src()
    assert "hmac.new(" in src, "Must use hmac.new() for signature validation"
    assert "hashlib.sha256" in src, "Must use SHA-256 for HMAC digest"


def test_reads_signature_header():
    src = _src()
    assert "x-hub-signature-256" in src, "Must read X-Hub-Signature-256 header"


def test_uses_compare_digest():
    src = _src()
    assert "hmac.compare_digest(" in src, "Must use constant-time comparison"


def test_raises_401_on_invalid_signature():
    src = _src()
    assert "401" in src, "Must return 401 on invalid signature"
