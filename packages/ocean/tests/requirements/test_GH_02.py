"""GH-02: GitHub connector normalizes PR events (opened/merged/closed)."""

from pathlib import Path

_ROOT = Path(__file__).parents[2]
_NORMALIZER = _ROOT / "services" / "github-connector" / "src" / "normalizer.py"


def _src() -> str:
    return _NORMALIZER.read_text()


def test_pr_opened_event_type():
    src = _src()
    assert '"pr.opened"' in src, "Must emit pr.opened for opened PRs"


def test_pr_merged_event_type():
    src = _src()
    assert '"pr.merged"' in src, "Must emit pr.merged for merged PRs"


def test_pr_closed_event_type():
    src = _src()
    assert '"pr.closed"' in src, "Must emit pr.closed for closed PRs"


def test_entity_id_includes_repo_and_pr_number():
    src = _src()
    assert "full_name" in src, "Must extract repo full_name"
    assert "pr_number" in src or "number" in src, "Must extract PR number"
    assert 'f"{repo_name}#{pr_number}"' in src, "entity_id must be repo#number"
