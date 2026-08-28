"""billing-state task 4.0 (DNA-1261): registration commands land state-bearing at entry state.

Offline against the real coercion path in `pulse_ledger.api`, like test_billing_boundary.py:
the wire boundary supplies `open_billing_episode`'s implied `to_state` ("open", derived from the
catalog's adjacency, never hand-listed), so the commit path folds the genesis and `current_state`
gains the episode — the behavior `test_commit.py` already pins for a declaration that carries
`to_state="open"`. Before this task, the command's body had no `to_state` at all (observed on
dev: three opened episodes with no `current_state` rows, every paired first transition rejected
as a genesis violation).

Synthetic ids throughout.
"""

from __future__ import annotations

from pulse_ledger.api import IMPLIED_TO_STATE_BY_EVENT_TYPE, coerce_declaration_fields
from pulse_ledger.validation import INITIAL_STATES

SUBJECT_KEY = "enr-1:2026-09-01"


def _open_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_type": "billing_episode",
        "subject_key": SUBJECT_KEY,
        "event_type": "open_billing_episode",
        "effective_at": "2026-09-01T00:00:00+00:00",
        "payload": {"month": "2026-09-01"},
    }
    body.update(overrides)
    return body


class TestImpliedEntryState:
    def test_open_billing_episode_gains_its_entry_state(self) -> None:
        coerced = coerce_declaration_fields(_open_body())
        assert coerced["to_state"] == "open"

    def test_an_explicit_to_state_always_wins(self) -> None:
        coerced = coerce_declaration_fields(_open_body(to_state="open"))
        assert coerced["to_state"] == "open"
        # A body carrying a different explicit value is passed through for the catalog to judge —
        # the mapping never overrides what a writer said.
        coerced = coerce_declaration_fields(_open_body(to_state="qualified"))
        assert coerced["to_state"] == "qualified"

    def test_no_blanket_rule_over_other_to_state_less_bodies(self) -> None:
        body = {
            "subject_type": "person",
            "subject_key": "person-1",
            "event_type": "mint_person",
            "effective_at": "2026-09-01T00:00:00+00:00",
        }
        coerced = coerce_declaration_fields(body)
        assert coerced.get("to_state") is None, "registry subjects stay non-state-bearing"

    def test_the_mapping_derives_from_the_catalog_adjacency(self) -> None:
        (derived,) = INITIAL_STATES["billing_episode"]
        assert {"open_billing_episode": derived} == IMPLIED_TO_STATE_BY_EVENT_TYPE
