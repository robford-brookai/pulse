"""GH-03: GitHub connector normalizes push events to commit.pushed."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_NORMALIZER = _ROOT / "services" / "github-connector" / "src" / "normalizer.py"


def _src() -> str:
    return _NORMALIZER.read_text()


def test_push_event_type():
    src = _src()
    assert '"commit.pushed"' in src, "Must emit commit.pushed for push events"


def test_push_entity_id_includes_sha():
    src = _src()
    assert "head_sha" in src, "Must extract head SHA from push payload"
    assert "head_sha[:12]" in src, "entity_id must use truncated SHA"


def test_push_payload_fields():
    src = _src()
    for field in ("repo", "ref", "head_sha", "commit_count", "pusher"):
        assert f'"{field}"' in src, f"Push payload must include {field}"


def test_source_system_is_github():
    src = _src()
    assert '"github"' in src, "source_system must be 'github'"
