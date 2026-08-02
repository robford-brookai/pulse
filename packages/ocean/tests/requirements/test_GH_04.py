"""GH-04: GitHub connector payloads contain no PHI fields."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_NORMALIZER = _ROOT / "services" / "github-connector" / "src" / "normalizer.py"
_RECEIVER = _ROOT / "services" / "github-connector" / "src" / "receiver.py"

PHI_FIELDS = {
    "email",
    "phone",
    "address",
    "date_of_birth",
    "ssn",
    "first_name",
    "last_name",
    "firstname",
    "lastname",
    "mobilephone",
    "dateOfBirth",
}


def test_normalizer_no_phi_in_payload_keys():
    src = _NORMALIZER.read_text()
    for field in PHI_FIELDS:
        assert f'"{field}"' not in src, f"Normalizer must not include PHI field: {field}"


def test_receiver_no_phi_in_payload_keys():
    src = _RECEIVER.read_text()
    for field in PHI_FIELDS:
        assert f'"{field}"' not in src, f"Receiver must not include PHI field: {field}"


def test_payload_uses_identifiers_only():
    """Verify payload fields are identifiers/metadata, not personal data."""
    src = _NORMALIZER.read_text()
    safe_fields = {
        "repo",
        "pr_number",
        "title",
        "author",
        "base_branch",
        "head_branch",
        "ref",
        "head_sha",
        "commit_count",
        "pusher",
    }
    for field in safe_fields:
        assert f'"{field}"' in src, f"Expected safe payload field: {field}"
