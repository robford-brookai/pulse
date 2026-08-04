"""Task 5.2: the S1 work orders pin real names, not forward references.

Before `pulse-ledger-core`, `design/delivery/pulse-s1-work-orders.md` pointed at S1.1 with
"confirm path" / "confirm endpoint" markers. This gate holds two properties now that the change
is built: no confirm marker survives, and every pinned name matches the constant or symbol the
code actually exports — so the doc cannot silently drift from the surface it names.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_ORDERS = REPO_ROOT / "design" / "delivery" / "pulse-s1-work-orders.md"


def _doc() -> str:
    return WORK_ORDERS.read_text(encoding="utf-8")


def test_no_confirm_markers_remain() -> None:
    """S1.1 shipped; nothing in the S1.2-S1.4 orders is left to confirm."""
    text = _doc().lower()
    for marker in ("confirm actual path", "confirm endpoint", "confirm path", "— confirm"):
        assert marker not in text, f"unresolved forward reference: {marker!r}"


def test_client_path_is_pinned_to_the_real_module() -> None:
    text = _doc()
    assert "packages/pulse-core/src/pulse_core/client.py" in text
    assert "packages/pulse-core/client.py" not in text  # the pre-build guess


def test_cursor_facility_matches_the_code_constant() -> None:
    from pulse_core.cursor import CURSOR_PATH_TEMPLATE

    assert CURSOR_PATH_TEMPLATE in _doc()


def test_command_paths_match_the_api_constants() -> None:
    from pulse_ledger.api import COMMANDS_PATH

    assert COMMANDS_PATH in _doc()


def test_read_surface_and_quarantine_table_are_pinned() -> None:
    text = _doc()
    assert "pulse_ledger.reads.enumerate_state" in text
    assert "pulse_ledger.identity" in text
    assert "ledger.review_queue" in text


def test_handler_signature_is_pinned() -> None:
    """The consumer convention names the real callable contract."""
    import pulse_core.client as client

    assert "pulse_core.client.consume" in _doc()
    assert hasattr(client, "consume")
    assert hasattr(client, "ConsumerHandler")


def test_pinned_symbols_exist() -> None:
    """Every module path the doc pins must import and export what the doc claims."""
    from pulse_core.client import PulseCoreClient
    from pulse_ledger.cursor import get_cursor, put_cursor
    from pulse_ledger.identity import find_candidates, lookup_identifier
    from pulse_ledger.reads import enumerate_state
    from pulse_ledger.review import list_review_queue, quarantine_subject, resolve_review

    for symbol in (
        PulseCoreClient,
        get_cursor,
        put_cursor,
        lookup_identifier,
        find_candidates,
        enumerate_state,
        list_review_queue,
        quarantine_subject,
        resolve_review,
    ):
        assert callable(symbol)


def test_publishes_contract_names_the_command_surface_and_its_gap() -> None:
    """`docs/contracts/publishes.md` documents the command/read surfaces, and carries the
    end-to-end caveat tasks 4.3 and 5.3 both flagged: the HTTP path does not yet accept
    `idempotency_key` or echo `replayed`."""
    text = (REPO_ROOT / "docs" / "contracts" / "publishes.md").read_text(encoding="utf-8")
    assert "POST /commands" in text
    assert "idempotency_key" in text
    assert "replayed" in text


def test_adr_0003_exists_and_is_accepted() -> None:
    adrs = sorted((REPO_ROOT / "docs" / "adr").glob("ADR-0003-*.md"))
    assert len(adrs) == 1, "exactly one ADR-0003 expected"
    text = adrs[0].read_text(encoding="utf-8")
    assert re.search(r"\*\*Status\*\*: Accepted", text)


def test_superseded_v1_docs_carry_supersession_notes() -> None:
    platform = REPO_ROOT / "design" / "platform"
    for name in ("event-envelope-spec.md", "state-catalog.md"):
        text = (platform / name).read_text(encoding="utf-8")
        assert "Superseded" in text, f"{name} lacks a supersession note"
        assert "pulse-ledger-core" in text, f"{name} supersession note does not name the change"
