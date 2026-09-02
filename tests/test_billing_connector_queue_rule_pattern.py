"""The billing connector's queue rule filter starts narrow (design.md decision 7, task 3.1).

Asserts the EventBridge rule pattern embedded in `scripts/billing-connector/
provision_billing_feed.sh` without any AWS emulator: the pattern is plain JSON, so this reads it
straight out of the script text and checks its shape. `scripts/ocean/provision_warehouse_feed.sh`
and `scripts/pulse-ledger/provision_projection_feed.sh` have no such test today (their own rule
matches every `source: ocean` event, so there is no filter shape to pin) — this connector's rule
is the first one narrow enough that drift is a real risk: widening the pattern accidentally
would deliver events the connector's own trigger allowlist (`billing_connector.service.
TRIGGER_SUBJECT_TYPES`) was never designed against.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "billing-connector" / "provision_billing_feed.sh"

#: The narrow filter design.md decision 7 specifies: patient-state events whose subject_type is
#: one of these four. billing_episode/coverage trigger evaluate -> declare; consent/enrollment
#: fold into facts and count deferred (design.md decision 4) — both halves need the event, so
#: both halves are in the filter.
EXPECTED_SUBJECT_TYPES = frozenset({"billing_episode", "coverage", "consent", "enrollment"})


def _embedded_pattern() -> dict[str, object]:
    """Extract the `EVENT_PATTERN='...'` literal from the script and parse it as JSON."""
    text = _SCRIPT.read_text()
    match = re.search(r"^EVENT_PATTERN='(.*)'$", text, re.MULTILINE)
    assert match is not None, "provision_billing_feed.sh must define EVENT_PATTERN='<json>'"
    return json.loads(match.group(1))


class TestRuleFilterPattern:
    def test_script_exists_and_is_executable(self) -> None:
        assert _SCRIPT.is_file()
        assert _SCRIPT.stat().st_mode & 0o111, "provision_billing_feed.sh must be executable"

    def test_pattern_is_valid_json(self) -> None:
        _embedded_pattern()  # raises on malformed JSON

    def test_pattern_matches_only_the_ocean_patient_state_domain(self) -> None:
        pattern = _embedded_pattern()
        assert pattern["source"] == ["ocean"]
        assert pattern["detail-type"] == ["patient-state"]

    def test_pattern_narrows_on_exactly_the_four_subject_types(self) -> None:
        pattern = _embedded_pattern()
        detail = pattern["detail"]
        assert isinstance(detail, dict)
        assert set(detail["subject_type"]) == EXPECTED_SUBJECT_TYPES, (
            "the queue rule filter must match exactly billing_episode/coverage/consent/enrollment "
            "(design.md decision 7) — no more, no fewer"
        )

    def test_trigger_allowlist_is_a_subset_of_the_queue_filter(self) -> None:
        """`billing_connector.service.TRIGGER_SUBJECT_TYPES` must never admit a subject type the
        queue rule does not even deliver — that would be a trigger nothing can ever reach."""
        from billing_connector.service import TRIGGER_SUBJECT_TYPES

        pattern = _embedded_pattern()
        detail = pattern["detail"]
        assert isinstance(detail, dict)
        delivered = set(detail["subject_type"])
        assert delivered >= TRIGGER_SUBJECT_TYPES
