"""Heal-back on rejection (twenty-projection task 3.1, `twenty-heal-back` spec).

A `rejected` disposition triggers one projection write restoring the card's status field to the
state of record — the same state the receipt names as unchanged. The heal goes through the
already-merged 2.1 projection writer (`twenty_projection.apply.ProjectionRestClient`), so it is
attributed to the projection identity and carries the encoded state value and nothing else. It
degrades exactly like the rejection note: a failed heal is one log line naming the card, and the
receipt is returned regardless.

Two seams, both socket-free: the route is tested against the `HealWriter` injection point (a
recording fake, like `RecordingCommentPoster`), and `api_server.build_heal_writer` is tested over
a scripted `httpx.MockTransport` — the same convention as the projection writer's own tests. The
echo-loop integration proof (the heal's own webhook bouncing back) is task 3.2's scope, not this
file's.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pulse_ledger import api_server
from pulse_ledger.api import TWENTY_WEBHOOK_PATH, HealWriter, create_app
from pulse_ledger.auth import (
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    TwentyWebhookConfig,
)
from pulse_ledger.commit import Declaration
from pulse_ledger.validation import IllegalTransitionError
from test_twenty_rejection_feedback import (
    FIXTURE_DEMOGRAPHICS,
    ILLEGAL_CARD_REF,
    ILLEGAL_FROM_STATE,
    CatalogCommitter,
    RecordingCommentPoster,
)
from twenty_fixtures import load_fixture_bytes, sign_fixture
from twenty_projection.apply import ProjectionWriteError

#: What the heal PATCH must carry for `illegal_drag.json`: the state of record (`active`, the
#: receipt's `from_state`) in Twenty's storage encoding, on the v1 board's status field, and no
#: other field — no as-of, no watermark; the heal has no ledger sequence in hand.
ILLEGAL_RECORD_ID = "twenty-record-patientprogram-0002"
ENCODED_STATE_OF_RECORD = "ACTIVE"
HEAL_PATCH_PATH = f"/rest/patientPrograms/{ILLEGAL_RECORD_ID}"

PROJECTION_TOKEN = "projection-identity-token"  # noqa: S105 — a synthetic test credential
TWENTY_BASE_URL = "https://twenty.example"


class RecordingHealWriter:
    """The heal seam's fake: records each (card_ref, state_of_record) call, or fails typed."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.heals: list[tuple[str, str]] = []

    def __call__(self, card_ref: str, state_of_record: str) -> None:
        self.heals.append((card_ref, state_of_record))
        if self.fail:
            raise ProjectionWriteError(card_ref, status_code=503)


@pytest.fixture
def secret() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def committer() -> CatalogCommitter:
    return CatalogCommitter()


@pytest.fixture
def comment_poster() -> RecordingCommentPoster:
    return RecordingCommentPoster()


@pytest.fixture
def heal_writer() -> RecordingHealWriter:
    return RecordingHealWriter()


def build_client(
    secret: str,
    committer: CatalogCommitter,
    comment_poster: RecordingCommentPoster | None,
    heal_writer: HealWriter | None,
) -> TestClient:
    app = create_app(
        committer=committer,
        comment_poster=comment_poster,
        heal_writer=heal_writer,
        registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": secrets.token_urlsafe(32)}),
        twenty_webhook=TwentyWebhookConfig.from_env({
            TWENTY_WEBHOOK_ENABLED_ENV: "true",
            TWENTY_WEBHOOK_SECRET_ENV: secret,
        }),
    )
    return TestClient(app)


@pytest.fixture
def client(
    secret: str,
    committer: CatalogCommitter,
    comment_poster: RecordingCommentPoster,
    heal_writer: RecordingHealWriter,
) -> Iterator[TestClient]:
    with build_client(secret, committer, comment_poster, heal_writer) as test_client:
        yield test_client


def post_fixture(client: TestClient, secret: str, name: str) -> tuple[int, dict[str, object]]:
    body = load_fixture_bytes(name)
    headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc))
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    return response.status_code, response.json()


class TestTheCardSnapsBackAfterAnIllegalDrag:
    """spec: "The card snaps back after an illegal drag"."""

    def test_a_rejection_triggers_one_heal_with_the_state_of_record(
        self, client: TestClient, secret: str, heal_writer: RecordingHealWriter
    ) -> None:
        status, body = post_fixture(client, secret, "illegal_drag")
        assert status == 200
        assert body["disposition"] == "rejected"
        assert heal_writer.heals == [(ILLEGAL_CARD_REF, ILLEGAL_FROM_STATE)]

    def test_the_heal_lands_alongside_the_rejection_note(
        self,
        client: TestClient,
        secret: str,
        heal_writer: RecordingHealWriter,
        comment_poster: RecordingCommentPoster,
    ) -> None:
        post_fixture(client, secret, "illegal_drag")
        assert len(heal_writer.heals) == 1
        assert len(comment_poster.posts) == 1

    def test_a_legal_drag_heals_nothing(
        self, client: TestClient, secret: str, heal_writer: RecordingHealWriter
    ) -> None:
        status, body = post_fixture(client, secret, "legal_drag")
        assert status == 200
        assert body["disposition"] == "committed"
        assert heal_writer.heals == []

    def test_a_first_declaration_rejection_has_no_state_to_restore(
        self, secret: str, comment_poster: RecordingCommentPoster, heal_writer: RecordingHealWriter
    ) -> None:
        """`from_state` is `None` for a subject's rejected first declaration — there is no state
        of record to write back, so the heal leg does nothing rather than guessing one."""

        class FirstDeclarationRefused(CatalogCommitter):
            def __call__(self, declaration: Declaration, idempotency_key: str | None) -> object:
                raise IllegalTransitionError(
                    declaration.subject_type,
                    None,
                    str(declaration.to_state),
                    reason="illegal initial state",
                )

        with build_client(secret, FirstDeclarationRefused(), comment_poster, heal_writer) as client:
            status, body = post_fixture(client, secret, "illegal_drag")
        assert status == 200
        assert body["disposition"] == "rejected"
        assert heal_writer.heals == []


class TestABrokenHealChannelStillRejectsCleanly:
    """spec: "A broken heal channel still rejects cleanly"."""

    @pytest.fixture
    def heal_writer(self) -> RecordingHealWriter:
        return RecordingHealWriter(fail=True)

    def test_the_receipt_is_still_returned(self, client: TestClient, secret: str) -> None:
        status, body = post_fixture(client, secret, "illegal_drag")
        assert status == 200
        assert body["disposition"] == "rejected"
        assert body["card_ref"] == ILLEGAL_CARD_REF
        assert body["from_state"] == ILLEGAL_FROM_STATE

    def test_the_note_still_posts(
        self, client: TestClient, secret: str, comment_poster: RecordingCommentPoster
    ) -> None:
        """The two feedback legs fail independently — a broken heal never silences the note."""
        post_fixture(client, secret, "illegal_drag")
        assert len(comment_poster.posts) == 1

    def test_the_failure_log_carries_the_card_reference_only(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="pulse_ledger.api"):
            post_fixture(client, secret, "illegal_drag")
        heal_lines = [record for record in caplog.records if "heal_failed" in record.getMessage()]
        assert len(heal_lines) == 1
        message = heal_lines[0].getMessage()
        assert ILLEGAL_CARD_REF in message
        assert "ProjectionWriteError" in message
        assert heal_lines[0].exc_info is None
        for name in FIXTURE_DEMOGRAPHICS:
            assert name not in message

    def test_an_unconfigured_heal_writer_degrades_the_same_way(
        self,
        secret: str,
        committer: CatalogCommitter,
        comment_poster: RecordingCommentPoster,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An app built without a heal writer still receipts — wiring absence is a logged heal
        failure, exactly the comment adapter's `CommentAdapterNotConfiguredError` posture."""
        with (
            build_client(secret, committer, comment_poster, None) as client,
            caplog.at_level(logging.WARNING, logger="pulse_ledger.api"),
        ):
            status, body = post_fixture(client, secret, "illegal_drag")
        assert status == 200
        assert body["disposition"] == "rejected"
        assert any("heal_failed" in record.getMessage() for record in caplog.records)


class ScriptedTransport:
    """A scripted Twenty REST edge: records every request, answers with one canned response."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status_code, json={})

        return httpx.MockTransport(handle)


class TestBuildHealWriter:
    """`api_server.build_heal_writer`: the projection-writer adapter behind the route's seam."""

    def test_no_projection_token_means_no_heal_writer(self) -> None:
        assert api_server.build_heal_writer({api_server.TWENTY_BASE_URL_ENV: TWENTY_BASE_URL}) is None

    def test_a_token_without_a_base_url_also_stays_unwired(self) -> None:
        environ = {api_server.PROJECTION_TWENTY_TOKEN_ENV: PROJECTION_TOKEN}
        assert api_server.build_heal_writer(environ) is None

    def _built(self, script: ScriptedTransport) -> HealWriter:
        environ = {
            api_server.PROJECTION_TWENTY_TOKEN_ENV: PROJECTION_TOKEN,
            api_server.TWENTY_BASE_URL_ENV: TWENTY_BASE_URL,
        }
        heal = api_server.build_heal_writer(environ, transport=script.transport())
        assert heal is not None
        return heal

    def test_one_patch_carries_the_encoded_state_of_record_and_nothing_else(self) -> None:
        script = ScriptedTransport()
        heal = self._built(script)
        heal(ILLEGAL_CARD_REF, ILLEGAL_FROM_STATE)
        assert len(script.requests) == 1
        request = script.requests[0]
        assert request.method == "PATCH"
        assert request.url.path == HEAL_PATCH_PATH
        assert json.loads(request.content) == {"lifecycleStatus": ENCODED_STATE_OF_RECORD}

    def test_the_write_is_attributed_to_the_projection_identity(self) -> None:
        script = ScriptedTransport()
        heal = self._built(script)
        heal(ILLEGAL_CARD_REF, ILLEGAL_FROM_STATE)
        assert script.requests[0].headers["Authorization"] == f"Bearer {PROJECTION_TOKEN}"

    def test_a_failed_patch_raises_the_projection_writers_typed_error(self) -> None:
        script = ScriptedTransport(status_code=503)
        heal = self._built(script)
        with pytest.raises(ProjectionWriteError):
            heal(ILLEGAL_CARD_REF, ILLEGAL_FROM_STATE)

    def test_a_card_on_an_unprojected_object_is_refused_by_name(self) -> None:
        script = ScriptedTransport()
        heal = self._built(script)
        with pytest.raises(LookupError):
            heal("mysteryObject:some-record-id", ILLEGAL_FROM_STATE)
        assert script.requests == []


class TestTheBuiltWriterBehindTheRoute:
    """The full leg over a scripted transport: rejection → one heal PATCH, receipt regardless."""

    def _client(
        self,
        secret: str,
        committer: CatalogCommitter,
        comment_poster: RecordingCommentPoster,
        script: ScriptedTransport,
    ) -> TestClient:
        environ = {
            api_server.PROJECTION_TWENTY_TOKEN_ENV: PROJECTION_TOKEN,
            api_server.TWENTY_BASE_URL_ENV: TWENTY_BASE_URL,
        }
        heal = api_server.build_heal_writer(environ, transport=script.transport())
        assert heal is not None
        return build_client(secret, committer, comment_poster, heal)

    def test_a_rejection_sends_one_heal_patch(
        self, secret: str, committer: CatalogCommitter, comment_poster: RecordingCommentPoster
    ) -> None:
        script = ScriptedTransport()
        with self._client(secret, committer, comment_poster, script) as client:
            status, body = post_fixture(client, secret, "illegal_drag")
        assert status == 200
        assert body["disposition"] == "rejected"
        patches = [request for request in script.requests if request.method == "PATCH"]
        assert len(patches) == 1
        assert patches[0].url.path == HEAL_PATCH_PATH
        assert json.loads(patches[0].content) == {"lifecycleStatus": ENCODED_STATE_OF_RECORD}

    def test_a_broken_transport_still_returns_the_receipt(
        self, secret: str, committer: CatalogCommitter, comment_poster: RecordingCommentPoster
    ) -> None:
        script = ScriptedTransport(status_code=503)
        with self._client(secret, committer, comment_poster, script) as client:
            status, body = post_fixture(client, secret, "illegal_drag")
        assert status == 200
        assert body["disposition"] == "rejected"
        assert body["from_state"] == ILLEGAL_FROM_STATE
