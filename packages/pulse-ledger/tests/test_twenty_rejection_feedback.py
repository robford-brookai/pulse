"""The rejection leg of the Twenty kanban route (task 3.2).

Task 3.1 wired the route as far as the committer and deliberately let an `IllegalTransitionError`
propagate to the app's 422 handler. What is under test here is the leg that replaces it: the
catalog's refusal becomes a 200 `rejected` disposition carrying a receipt, a card comment goes out
through the 2.2 adapter, and neither the receipt, the comment, nor any log line on any failure
path carries a byte of the webhook payload.

No database and no socket: the committer is a fake that raises the real `IllegalTransitionError`,
and the comment adapter is faked at the `CommentPoster` seam rather than over HTTP (the HTTP
boundary itself is `test_twenty_client.py`'s).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pulse_ledger.api import TWENTY_WEBHOOK_PATH, create_app
from pulse_ledger.auth import (
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    TwentyWebhookConfig,
)
from pulse_ledger.commit import CommitResult, Declaration
from pulse_ledger.fold import FoldedState
from pulse_ledger.twenty.client import CommentPostError, RejectionReceipt, format_rejection_comment
from pulse_ledger.twenty.mapping import V1_BOARD_MAPPINGS, Drag, RecordRef, interpret
from pulse_ledger.validation import IllegalTransitionError
from twenty_fixtures import load_fixture_bytes, sign_fixture

NOW = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)

#: Every fixture record carries this first name (`fixtures/twenty/README.md`), so one string
#: catches a leak from any case. The case-specific surnames are listed beside it so a scan names
#: what it is looking for rather than trusting a single token.
FIXTURE_DEMOGRAPHICS = (
    "Canary",
    "CareCoordinator",
    "LegalDrag",
    "IllegalDrag",
    "MissingCanonical",
    "NoopCreate",
    "NoopDelete",
    "NoopNonStatus",
    "NoopUnmapped",
)

#: What `illegal_drag.json` maps to: the backwards drag, its card, and the subject behind it.
ILLEGAL_CARD_REF = "patientProgram:twenty-record-patientprogram-0002"
ILLEGAL_FROM_STATE = "activated"
ILLEGAL_TO_STATE = "registered"
ILLEGAL_SUBJECT_TYPE = "enrollment"

#: The board vocabulary the fixtures are written in, and the one edge that is legal in it. The
#: fake committer decides against this rather than the generated catalog: the fixtures project a
#: Twenty board's column names, and what is under test is the route's handling of a refusal, not
#: which refusals the catalog issues (that is `test_validation.py`'s).
FIXTURE_ADJACENCY: Mapping[str, frozenset[str]] = {
    "registered": frozenset({"enrolled"}),
    "enrolled": frozenset({"activated"}),
    "activated": frozenset(),
}

_EVENT_ID_BASE = uuid.UUID("018f5a1e-1111-7000-8000-000000000000").int


def _current_state(to_state: str) -> str:
    """The state a subject dragged *to* `to_state` must have been sitting in.

    The real committer folds this out of the ledger; the fake reads it back off the fixture's own
    board vocabulary so the receipt's `from_state` is a real value rather than a constant.
    """
    return {"enrolled": "registered", "registered": "activated", "activated": "enrolled"}[to_state]


class CatalogCommitter:
    """A fake commit path that refuses illegal transitions exactly as the real one does.

    `effects` counts events actually written — the rejection scenario's "no event" assertion is
    about this number, not about whether the call happened.
    """

    def __init__(self) -> None:
        self.declarations: list[Declaration] = []
        self._by_key: dict[str, CommitResult] = {}

    @property
    def calls(self) -> int:
        return len(self.declarations)

    @property
    def effects(self) -> int:
        return len(self._by_key)

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
            return dataclasses.replace(self._by_key[idempotency_key], replayed=True)
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
    """The 2.2 adapter at its injection seam: records what was posted, or fails like the real one.

    `fail` makes every post raise `CommentPostError` — the typed error `TwentyCommentClient`
    raises once its retries are spent, so the route's handling is tested against the real failure
    type rather than a stand-in.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.posts: list[tuple[str, str]] = []

    @property
    def bodies(self) -> list[str]:
        return [body for _, body in self.posts]

    def __call__(self, card_ref: str, body: str) -> None:
        self.posts.append((card_ref, body))
        if self.fail:
            raise CommentPostError(card_ref, attempts=4, status_code=503)


@pytest.fixture
def secret() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def committer() -> CatalogCommitter:
    return CatalogCommitter()


@pytest.fixture
def comment_poster() -> RecordingCommentPoster:
    return RecordingCommentPoster()


@contextmanager
def build_client(
    secret: str,
    committer: CatalogCommitter,
    comment_poster: RecordingCommentPoster | None,
) -> Iterator[TestClient]:
    """One enabled-route app, with the comment adapter injected — or deliberately left unwired."""
    app = create_app(
        committer=committer,
        comment_poster=comment_poster,
        registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": secrets.token_urlsafe(32)}),
        twenty_webhook=TwentyWebhookConfig.from_env({
            TWENTY_WEBHOOK_ENABLED_ENV: "true",
            TWENTY_WEBHOOK_SECRET_ENV: secret,
        }),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(secret: str, committer: CatalogCommitter, comment_poster: RecordingCommentPoster) -> Iterator[TestClient]:
    with build_client(secret, committer, comment_poster) as test_client:
        yield test_client


def post_fixture(client: TestClient, secret: str, name: str) -> tuple[int, dict[str, object]]:
    """Deliver a named fixture as Twenty would, validly signed. Returns status and body."""
    body = load_fixture_bytes(name)
    headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc))
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    return response.status_code, response.json()


class TestIllegalTransitionYieldsAReceiptAndNoEvent:
    """spec: "Illegal transition yields a receipt and no event"."""

    def test_the_response_is_a_success_carrying_the_rejected_disposition(self, client: TestClient, secret: str) -> None:
        """200, not 422: Twenty classifies 2xx/non-2xx, so a 4xx buys a retry storm (decision 5)."""
        status, body = post_fixture(client, secret, "illegal_drag")

        assert status == 200
        assert body["disposition"] == "rejected"

    def test_no_event_is_written(self, client: TestClient, secret: str, committer: CatalogCommitter) -> None:
        post_fixture(client, secret, "illegal_drag")

        assert committer.effects == 0

    def test_the_receipt_names_the_transition_reason_and_catalog_version(self, client: TestClient, secret: str) -> None:
        _, body = post_fixture(client, secret, "illegal_drag")

        assert body["from_state"] == ILLEGAL_FROM_STATE
        assert body["to_state"] == ILLEGAL_TO_STATE
        assert ILLEGAL_SUBJECT_TYPE in str(body["reason"])
        assert body["catalog_version"] == IllegalTransitionError("x", None, "y", reason="z").catalog_version

    def test_the_receipt_names_the_card_it_came_from(self, client: TestClient, secret: str) -> None:
        """The card ref comes from the mapping, the rest from the error — nothing from the payload."""
        _, body = post_fixture(client, secret, "illegal_drag")

        assert body["card_ref"] == ILLEGAL_CARD_REF

    def test_a_legal_drag_on_the_same_app_still_commits(
        self, client: TestClient, secret: str, comment_poster: RecordingCommentPoster
    ) -> None:
        """The rejection leg is a branch, not a gate: the committed path is untouched by it."""
        status, body = post_fixture(client, secret, "legal_drag")

        assert status == 200
        assert body["disposition"] == "committed"
        assert comment_poster.posts == []


class TestTheRejectionPostsOneComment:
    """The route's half of the comment contract; the comment's own content is 2.2's test."""

    def test_the_adapter_is_invoked_once_with_the_card_ref_and_the_formatted_body(
        self, client: TestClient, secret: str, comment_poster: RecordingCommentPoster
    ) -> None:
        _, body = post_fixture(client, secret, "illegal_drag")
        receipt = RejectionReceipt(
            card_ref=str(body["card_ref"]),
            from_state=None if body["from_state"] is None else str(body["from_state"]),
            to_state=str(body["to_state"]),
            reason=str(body["reason"]),
            catalog_version=str(body["catalog_version"]),
        )

        assert comment_poster.posts == [(ILLEGAL_CARD_REF, format_rejection_comment(receipt))]

    def test_the_comment_body_carries_the_states_and_the_reason(
        self, client: TestClient, secret: str, comment_poster: RecordingCommentPoster
    ) -> None:
        post_fixture(client, secret, "illegal_drag")
        posted = comment_poster.bodies[0]

        assert ILLEGAL_FROM_STATE in posted
        assert ILLEGAL_TO_STATE in posted
        assert "not in the catalog adjacency" in posted


class TestACommentFailureNeverLosesTheReceipt:
    """spec: "A comment failure never loses the receipt"."""

    @pytest.fixture
    def comment_poster(self) -> RecordingCommentPoster:
        return RecordingCommentPoster(fail=True)

    def test_the_receipt_is_still_returned(self, client: TestClient, secret: str) -> None:
        status, body = post_fixture(client, secret, "illegal_drag")

        assert status == 200
        assert body["disposition"] == "rejected"
        assert body["from_state"] == ILLEGAL_FROM_STATE
        assert body["to_state"] == ILLEGAL_TO_STATE
        assert body["card_ref"] == ILLEGAL_CARD_REF

    def test_the_failure_is_logged_with_the_card_reference_only(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture, comment_poster: RecordingCommentPoster
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            post_fixture(client, secret, "illegal_drag")

        failure_lines = [
            record.getMessage() for record in caplog.records if "comment_post_failed" in record.getMessage()
        ]
        assert len(failure_lines) == 1
        logged = failure_lines[0]
        assert ILLEGAL_CARD_REF in logged
        assert comment_poster.bodies[0] not in logged
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in logged

    def test_an_adapter_that_was_never_configured_degrades_the_same_way(
        self, secret: str, committer: CatalogCommitter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An app built without a comment adapter still returns receipts — feedback degrades, not correctness."""
        with build_client(secret, committer, None) as test_client, caplog.at_level(logging.DEBUG):
            status, body = post_fixture(test_client, secret, "illegal_drag")

        assert status == 200
        assert body["disposition"] == "rejected"
        assert "comment_post_failed" in "\n".join(record.getMessage() for record in caplog.records)


class TestTheHandlerExceptionPath:
    """The flagged PHI exit (design Risks a): a crash past the door logs identifiers, not the body."""

    @pytest.fixture
    def committer(self) -> CatalogCommitter:
        class ExplodingCommitter(CatalogCommitter):
            def __call__(self, _declaration: Declaration, _idempotency_key: str | None) -> CommitResult:
                # The message deliberately carries a fixture demographic: a handler that logs the
                # exception rather than its type would leak it, and this is the assertion that catches it.
                msg = "connection lost while committing Canary IllegalDrag"
                raise RuntimeError(msg)

        return ExplodingCommitter()

    def test_the_delivery_is_not_acknowledged(self, client: TestClient, secret: str) -> None:
        """A drag that did not get handled must not read as handled — Twenty should retry it."""
        status, body = post_fixture(client, secret, "illegal_drag")

        assert status == 500
        detail = body["detail"]
        assert isinstance(detail, dict)
        assert detail["card_ref"] == ILLEGAL_CARD_REF
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in json.dumps(body)

    def test_the_log_names_the_record_and_the_disposition_only(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            post_fixture(client, secret, "illegal_drag")

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "disposition=error" in logged
        assert ILLEGAL_CARD_REF in logged
        assert "RuntimeError" in logged
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in logged

    def test_an_unbuildable_declaration_does_not_reach_the_422_handler(
        self,
        secret: str,
        caplog: pytest.LogCaptureFixture,
        comment_poster: RecordingCommentPoster,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`DeclarationError`'s message quotes the offending value — on this route that value is payload."""

        def bad_mapping(payload: object, mappings: object) -> Drag:
            fields = dict(interpret(payload, V1_BOARD_MAPPINGS).declaration_fields)  # type: ignore[union-attr]
            fields["effective_at"] = f"Canary IllegalDrag admitted {fields['effective_at']}"
            return Drag(
                declaration_fields=fields,
                idempotency_key="k",
                card_ref=RecordRef("patientProgram", "twenty-record-patientprogram-0002"),
                member_ref=None,
            )

        monkeypatch.setattr("pulse_ledger.api.interpret", bad_mapping)
        with build_client(secret, CatalogCommitter(), comment_poster) as test_client, caplog.at_level(logging.DEBUG):
            status, body = post_fixture(test_client, secret, "illegal_drag")

        assert status == 500
        rendered = json.dumps(body) + "\n".join(record.getMessage() for record in caplog.records)
        assert "disposition=error" in rendered, "it must take the sanitised exit, not the 422 handler"
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in rendered

    def test_no_traceback_is_rendered_into_the_log(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`logger.exception` here would serialise the frame that holds the payload."""
        with caplog.at_level(logging.DEBUG):
            post_fixture(client, secret, "illegal_drag")

        assert all(record.exc_info is None for record in caplog.records)


class TestNoFixturePayloadContentAcrossFailurePaths:
    """spec: "No fixture payload content in logs or receipts across failure paths"."""

    #: Every disposition the route can reach, in one sweep: commit, replay, no-op, unmapped,
    #: rejection, and malformed. The comment-failure path is swept separately below — it needs a
    #: failing adapter, and a failure that only leaks on the retry-exhausted branch would slip
    #: through a happy-adapter scan.
    FIXTURES = (
        "legal_drag",
        "redelivery_duplicate",
        "noop_create",
        "noop_delete",
        "noop_non_status_update",
        "noop_unmapped_object",
        "missing_canonical_id",
        "illegal_drag",
        "malformed_body",
    )

    def _sweep(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture, poster: RecordingCommentPoster
    ) -> str:
        """Drive every disposition and return logs, response bodies, and comment bodies as one string."""
        bodies: list[dict[str, object]] = []
        with caplog.at_level(logging.DEBUG):
            for fixture in self.FIXTURES:
                _, body = post_fixture(client, secret, fixture)
                bodies.append(body)
        return "\n".join([
            *(record.getMessage() for record in caplog.records),
            json.dumps(bodies, default=str),
            *poster.bodies,
        ])

    def test_a_happy_adapter_sweep_leaks_nothing(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture, comment_poster: RecordingCommentPoster
    ) -> None:
        swept = self._sweep(client, secret, caplog, comment_poster)

        assert "disposition=rejected" in swept, "the sweep must actually reach the rejection path"
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in swept

    def test_a_failing_adapter_sweep_leaks_nothing(
        self, secret: str, committer: CatalogCommitter, caplog: pytest.LogCaptureFixture
    ) -> None:
        poster = RecordingCommentPoster(fail=True)
        with build_client(secret, committer, poster) as test_client:
            swept = self._sweep(test_client, secret, caplog, poster)

        assert "comment_post_failed" in swept, "the sweep must actually reach the comment-failure path"
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in swept

    def test_the_unmapped_line_still_names_the_record_and_board_only(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Owned by task 3.1; asserted here because this scan is where a regression would surface."""
        with caplog.at_level(logging.INFO):
            post_fixture(client, secret, "missing_canonical_id")

        unmapped = [record.getMessage() for record in caplog.records if "disposition=unmapped" in record.getMessage()]
        assert len(unmapped) == 1
        assert "twenty-record-patientprogram-0003" in unmapped[0]
        assert "patientProgram.lifecycleStatus" in unmapped[0]
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in unmapped[0]
