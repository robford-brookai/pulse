#!/usr/bin/env python
"""Demo 2's kanban leg (task 4.1) — the Twenty webhook ingress, offline per the demo convention.

Per the roadmap's demo convention (`design/delivery/pulse-program-roadmap.md` #Demo breakpoints):
a runnable script under `scripts/demo/`, exits nonzero on any failed assertion, stays out of
`task check` (task 4.3's verification wrap runs it explicitly). Unlike Demo 1, this needs no
LocalStack, no Postgres, no Docker, and no live Twenty instance — the webhook route's app is built
in-process with a fake committer and a fake comment transport, the same seams
`test_twenty_webhook_route.py` and `test_twenty_rejection_feedback.py` inject at, so this is a real
exercise of `pulse_ledger.api`'s enabled route rather than a rebuild of its logic.

Drives three of the change's Demo 2 assertions against `twenty_fixtures`' synthetic, HMAC-signed
payloads (task 1.1):

1. A validly signed legal drag commits end to end — the response carries the committed event id
   (twenty-drag-command spec: "A signed synthetic drag commits end to end").
2. An invalid drag rejects with a receipt naming the violated transition and catalog reason, and
   posts exactly one comment to the originating card (twenty-rejection-feedback spec: "Illegal
   transition yields a receipt and no event"; "The comment names the transition and reason,
   nothing else").
3. A tampered signature is rejected as unauthenticated before any processing — a 401, no committer
   call (twenty-webhook-auth spec: "A tampered body is rejected without processing").

**The board vocabulary (settled by the 4.2 capture; task 5.2).** The fixtures now carry the wire
encoding Twenty actually sends (`ACTIVE`, `PENDING_START` — UPPER_SNAKE per
`pulse_core.twenty_validate.encode_option_value`), and the mapping decodes them to the ratified
`enrollment` catalog states (`pending_start`/`active`/`on_hold`/`ended`). This script's
`BoardVocabularyCommitter` restates that adjacency rather than importing the generated catalog,
so its "invalid drag" is a decision the route itself makes against a real adjacency, not a
hardcoded rejection — the same seam `test_twenty_rejection_feedback.py` fakes at.

PHI posture: every receipt and comment printed below is built exclusively from `IllegalTransitionError`
fields, a card reference, and a disposition — the same fields the route itself is restricted to
(twenty-rejection-feedback spec, "Nothing that leaves the process carries payload content"). No
fixture demographic (`Canary`, `LegalDrag`, `IllegalDrag`, ...) ever reaches anything this script
prints.

Usage:
    scripts/demo/demo2_kanban_drag.py
    scripts/demo/demo2_kanban_drag.py --help
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
PULSE_LEDGER_TESTS_DIR = REPO_ROOT / "packages" / "pulse-ledger" / "tests"

# `twenty_fixtures` is a test-only helper (packages/pulse-ledger/tests/twenty_fixtures.py) that
# owns the fixture name -> bytes/signature mapping; this script reuses it rather than hand-opening
# a fixture path or re-rolling the HMAC, the same convention `demo2_identity_matcher.py` follows
# for `fixtures.loader`.
sys.path.insert(0, str(PULSE_LEDGER_TESTS_DIR))

from pulse_ledger.api import TWENTY_WEBHOOK_PATH, create_app  # noqa: E402
from pulse_ledger.auth import (  # noqa: E402
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    TwentyWebhookConfig,
)
from pulse_ledger.commit import CommitResult, Declaration  # noqa: E402
from pulse_ledger.fold import FoldedState  # noqa: E402
from pulse_ledger.validation import IllegalTransitionError  # noqa: E402
from twenty_fixtures import load_fixture_bytes, sign_fixture  # noqa: E402 - path insert above must run first

#: A fixed instant for the fake committer's `recorded_at` — reproducible across runs, matching
#: `test_twenty_webhook_route.py`'s `NOW`. Signatures are timestamped against the real clock
#: (`_now()`, below) instead: `webhook.verify`'s freshness window is checked against wall-clock
#: time, not this constant, so signing against a fixed past instant would go stale.
NOW = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)

_EVENT_ID_BASE = uuid.UUID("018f5a1e-4000-7000-8000-000000000000").int


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


#: The `enrollment` catalog adjacency the fixtures are written in (`fixtures/twenty/README.md`) —
#: see the module docstring's vocabulary note. Identical in shape to
#: `test_twenty_rejection_feedback.py`'s `FIXTURE_ADJACENCY`, restated here rather than imported
#: from a test module this script otherwise avoids depending on.
FIXTURE_ADJACENCY: Mapping[str, frozenset[str]] = {
    "pending_start": frozenset({"active", "ended"}),
    "active": frozenset({"on_hold", "ended"}),
    "on_hold": frozenset({"active", "ended"}),
    "ended": frozenset(),
}


class DemoAssertionError(AssertionError):
    """One of Demo 2's three kanban assertions failed. The script exits nonzero when this is raised."""


def _check(condition: object, message: str) -> None:
    if not condition:
        raise DemoAssertionError(message)


def _current_state(to_state: str) -> str:
    """The state a subject dragged *to* `to_state` must have been sitting in, per the fixture board.

    Mirrors `test_twenty_rejection_feedback.py`'s helper of the same name: the fake committer reads
    the "prior" state off the board's own vocabulary rather than folding a real ledger history,
    since this demo commits nothing to a database.
    """
    return {"active": "pending_start", "pending_start": "active", "on_hold": "active", "ended": "active"}[to_state]


class BoardVocabularyCommitter:
    """A fake commit path that refuses transitions the fixture board's adjacency does not permit.

    Mirrors `test_twenty_rejection_feedback.py`'s `CatalogCommitter` at the same injection seam
    `pulse_ledger.api.Committer` — no database, no socket, the real `IllegalTransitionError` raised
    for a real (if fixture-scoped) reason, so the route's rejection-handling runs unmodified.
    """

    def __init__(self) -> None:
        self.declarations: list[Declaration] = []
        self._by_key: dict[str, CommitResult] = {}

    def __call__(self, declaration: Declaration, idempotency_key: str | None) -> CommitResult:
        self.declarations.append(declaration)
        to_state = str(declaration.to_state)
        from_state = _current_state(to_state)
        if to_state not in FIXTURE_ADJACENCY.get(from_state, frozenset()):
            raise IllegalTransitionError(
                declaration.subject_type,
                from_state,
                to_state,
                reason=(
                    f"illegal transition for {declaration.subject_type!r}: {from_state!r} -> "
                    f"{to_state!r} is not in the catalog adjacency"
                ),
            )
        if idempotency_key is not None and idempotency_key in self._by_key:
            return replace(self._by_key[idempotency_key], replayed=True)
        event_id = uuid.UUID(int=_EVENT_ID_BASE + len(self._by_key) + 1)
        result = CommitResult(
            event_id=event_id,
            recorded_at=NOW,
            rule_version="appendix-c-v0.7",
            outbox_seq=len(self._by_key) + 1,
            state=FoldedState(state=to_state, effective_at=NOW, recorded_at=NOW, event_id=event_id),
        )
        if idempotency_key is not None:
            self._by_key[idempotency_key] = result
        return result


class RecordingCommentPoster:
    """The 2.2 comment adapter's injection seam: records what would have posted to the card.

    No HTTP, no `PULSE_LEDGER_TWENTY_API_TOKEN` — that boundary is `test_twenty_client.py`'s.
    """

    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []

    def __call__(self, card_ref: str, body: str) -> None:
        self.posts.append((card_ref, body))


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)


def _build_app(secret: str, committer: BoardVocabularyCommitter, comment_poster: RecordingCommentPoster) -> FastAPI:
    return create_app(
        committer=committer,
        comment_poster=comment_poster,
        registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}DEMO": secrets.token_urlsafe(32)}),
        twenty_webhook=TwentyWebhookConfig.from_env({
            TWENTY_WEBHOOK_ENABLED_ENV: "true",
            TWENTY_WEBHOOK_SECRET_ENV: secret,
        }),
    )


def _print_receipt(step: str, body: Mapping[str, Any]) -> None:
    print(json.dumps({"step": step, **body}))


def step_committed_drag(client: TestClient, secret: str) -> None:
    """1/3: a validly signed legal drag commits, and the response carries the committed event id."""
    body = load_fixture_bytes("legal_drag")
    headers = sign_fixture(secret, body, now=_now())
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    payload = response.json()
    _print_receipt("committed_drag", payload)

    _check(response.status_code == 200, f"legal drag expected 200, got {response.status_code}")
    _check(
        payload.get("disposition") == "committed",
        f"expected disposition 'committed', got {payload.get('disposition')!r}",
    )
    _check(payload.get("event_id") is not None, "committed response carried no event id")


def step_rejected_drag(client: TestClient, secret: str, comment_poster: RecordingCommentPoster) -> None:
    """2/3: an invalid drag rejects with a receipt and posts a comment to the originating card."""
    body = load_fixture_bytes("illegal_drag")
    headers = sign_fixture(secret, body, now=_now())
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    payload = response.json()
    _print_receipt("rejected_drag", payload)

    _check(
        response.status_code == 200,
        f"illegal drag expected 200 (a rejection receipt, not an error status), got {response.status_code}",
    )
    _check(
        payload.get("disposition") == "rejected",
        f"expected disposition 'rejected', got {payload.get('disposition')!r}",
    )
    _check(payload.get("from_state") is not None, "rejection receipt carried no from_state")
    _check(payload.get("to_state") is not None, "rejection receipt carried no to_state")
    _check(bool(payload.get("reason")), "rejection receipt carried no catalog reason")
    _check(bool(payload.get("catalog_version")), "rejection receipt carried no catalog version")

    _check(len(comment_poster.posts) == 1, f"expected exactly one card comment, found {len(comment_poster.posts)}")
    card_ref, comment_body = comment_poster.posts[0]
    print(json.dumps({"step": "rejection_comment", "card_ref": card_ref, "body": comment_body}))
    _check(card_ref == payload.get("card_ref"), "the comment was posted to a different card than the receipt names")


def step_tampered_signature(client: TestClient, secret: str, committer: BoardVocabularyCommitter) -> None:
    """3/3: a tampered signature is a 401, and the committer is never reached."""
    calls_before = len(committer.declarations)
    body = load_fixture_bytes("legal_drag")
    headers = sign_fixture(secret, body, now=_now(), kind="tampered")
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    _print_receipt("tampered_signature", response.json())

    _check(response.status_code == 401, f"tampered signature expected 401, got {response.status_code}")
    _check(len(committer.declarations) == calls_before, "a tampered signature reached the committer")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    parser.parse_args(argv)

    print("=== Demo 2: Twenty kanban ingress (the Demo 2 kanban leg) ===")
    secret = secrets.token_urlsafe(32)
    committer = BoardVocabularyCommitter()
    comment_poster = RecordingCommentPoster()
    app = _build_app(secret, committer, comment_poster)

    try:
        with TestClient(app) as client:
            print("\n[1/3] a validly signed legal drag commits to a committed event id")
            step_committed_drag(client, secret)

            print("\n[2/3] an invalid drag rejects with a receipt and posts a card comment")
            step_rejected_drag(client, secret, comment_poster)

            print("\n[3/3] a tampered signature is rejected as unauthenticated (401)")
            step_tampered_signature(client, secret, committer)
    except DemoAssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\n=== Demo 2: all three kanban assertions passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
