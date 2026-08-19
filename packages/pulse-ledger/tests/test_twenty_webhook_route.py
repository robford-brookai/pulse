"""The enabled Twenty kanban route, end to end at the HTTP edge (task 3.1).

The door (`test_api_auth.py`) and the mapping core (`test_twenty_mapping.py`) are each tested on
their own. What is under test here is the wiring between them and the commit path: that auth runs
before anything else, that attribution is the webhook principal's rather than the payload's, and
that every disposition comes back as a 200 Twenty will not retry.

No database and no socket — the committer is a fake, as it is for every other suite at this
boundary, and the fixtures are task 1.1's synthetic payloads signed through `twenty_fixtures`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pulse_ledger.api import TWENTY_WEBHOOK_PATH, create_app
from pulse_ledger.auth import (
    SIGNATURE_HEADER,
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    TwentyWebhookConfig,
)
from pulse_ledger.commit import CommitResult, Declaration
from pulse_ledger.fold import FoldedState
from pulse_ledger.twenty.mapping import WEBHOOK_WRITER_ID
from twenty_fixtures import SignatureKind, load_fixture_bytes, sign_fixture

NOW = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)

#: The fixture demographics, verbatim. Recognisable fakes, and the strings the PHI scans look for.
FIXTURE_DEMOGRAPHICS = ("Canary", "LegalDrag", "CareCoordinator")

#: The workspace member who dragged the fixture card, and the canonical spine ID behind it.
FIXTURE_MEMBER_ID = "wsm-0001-canary-nurse"
FIXTURE_CANONICAL_ID = "DIM_PATIENT_CONFORMED-000101"
FIXTURE_RECORD_ID = "twenty-record-patientprogram-0001"
UNMAPPED_RECORD_ID = "twenty-record-patientprogram-0003"

_EVENT_ID_BASE = uuid.UUID("018f5a1e-0000-7000-8000-000000000000").int


class RecordingCommitter:
    """A fake commit path that mirrors `commit_idempotent`'s replay contract.

    `calls` counts everything that reached it; `effects` counts the commits that actually produced
    an event. The redelivery scenario is exactly the case where those two numbers differ, so they
    are counted separately rather than inferred from one list.
    """

    def __init__(self) -> None:
        self.declarations: list[Declaration] = []
        self.keys: list[str | None] = []
        self._by_key: dict[str, CommitResult] = {}

    @property
    def calls(self) -> int:
        return len(self.declarations)

    @property
    def effects(self) -> int:
        return len(self._by_key)

    def __call__(self, declaration: Declaration, idempotency_key: str | None) -> CommitResult:
        self.declarations.append(declaration)
        self.keys.append(idempotency_key)
        if idempotency_key is not None and idempotency_key in self._by_key:
            return dataclasses.replace(self._by_key[idempotency_key], replayed=True)
        event_id = uuid.UUID(int=_EVENT_ID_BASE + len(self._by_key) + 1)
        result = CommitResult(
            event_id=event_id,
            recorded_at=NOW,
            rule_version="appendix-c-v0.7",
            outbox_seq=len(self._by_key) + 1,
            state=FoldedState(state="active", effective_at=NOW, recorded_at=NOW, event_id=event_id),
        )
        if idempotency_key is not None:
            self._by_key[idempotency_key] = result
        return result


@pytest.fixture
def secret() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def committer() -> RecordingCommitter:
    return RecordingCommitter()


@pytest.fixture
def client(secret: str, committer: RecordingCommitter) -> Iterator[TestClient]:
    app = create_app(
        committer=committer,
        registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": secrets.token_urlsafe(32)}),
        twenty_webhook=TwentyWebhookConfig.from_env({
            TWENTY_WEBHOOK_ENABLED_ENV: "true",
            TWENTY_WEBHOOK_SECRET_ENV: secret,
        }),
    )
    with TestClient(app) as test_client:
        yield test_client


def post_fixture(
    client: TestClient,
    secret: str,
    name: str,
    *,
    kind: SignatureKind = "valid",
) -> tuple[int, dict[str, object]]:
    """Deliver a named fixture as Twenty would, signed the given way. Returns status and body."""
    body = load_fixture_bytes(name)
    headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc), kind=kind)
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    return response.status_code, response.json()


class TestAValidlySignedDragCommits:
    """spec: "A validly signed request is processed"; spec: "A signed synthetic drag commits end to end"."""

    def test_it_reaches_the_mapping_and_commits(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        status, body = post_fixture(client, secret, "legal_drag")

        assert status == 200
        assert body["disposition"] == "committed"
        assert committer.calls == 1

    def test_the_response_carries_the_committed_event_id(self, client: TestClient, secret: str) -> None:
        _, body = post_fixture(client, secret, "legal_drag")

        assert uuid.UUID(str(body["event_id"])) == uuid.UUID(int=_EVENT_ID_BASE + 1)
        assert body["replayed"] is False

    def test_the_declaration_is_the_mapped_transition(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        post_fixture(client, secret, "legal_drag")
        declaration = committer.declarations[0]

        assert declaration.event_type == "declare_transition"
        assert declaration.subject_type == "enrollment"
        assert declaration.subject_key == FIXTURE_CANONICAL_ID
        # The wire carried `ACTIVE`; the mapping decodes to the catalog's own vocabulary.
        assert declaration.to_state == "active"

    def test_the_idempotency_key_reaches_the_committer(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        """The D16 key is derived from the delivery, not left to the committer to invent."""
        post_fixture(client, secret, "legal_drag")

        assert committer.keys[0] is not None
        assert committer.keys[0].startswith(WEBHOOK_WRITER_ID)


class TestTheDraggingUserIsProvenanceNotActor:
    """spec: "The dragging user is provenance, not actor"."""

    @pytest.fixture
    def declaration(self, client: TestClient, secret: str, committer: RecordingCommitter) -> Declaration:
        post_fixture(client, secret, "legal_drag")
        return committer.declarations[0]

    def test_the_actor_is_the_webhook_principal(self, declaration: Declaration) -> None:
        assert declaration.actor_type == "system"
        assert declaration.actor_id == WEBHOOK_WRITER_ID
        assert declaration.producer == WEBHOOK_WRITER_ID

    def test_the_workspace_member_appears_only_in_evidence(self, declaration: Declaration) -> None:
        assert declaration.evidence is not None
        assert FIXTURE_MEMBER_ID in json.dumps(dict(declaration.evidence))
        attribution = (declaration.actor_id, declaration.actor_type, declaration.producer, declaration.actor_authority)
        assert all(value != FIXTURE_MEMBER_ID for value in attribution)

    def test_no_payload_demographic_reaches_the_declaration(self, declaration: Declaration) -> None:
        rendered = json.dumps({
            "evidence": dict(declaration.evidence or {}),
            "payload": dict(declaration.payload),
            "subject_key": declaration.subject_key,
        })
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in rendered


class TestATamperedBodyIsRejectedWithoutProcessing:
    """spec: "A tampered body is rejected without processing"."""

    def test_it_is_unauthenticated_and_nothing_commits(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc), kind="tampered")

        response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)

        assert response.status_code == 401
        assert committer.calls == 0

    def test_neither_the_body_nor_the_signature_is_logged(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc), kind="tampered")

        with caplog.at_level(logging.DEBUG):
            client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert headers[SIGNATURE_HEADER] not in logged
        assert FIXTURE_CANONICAL_ID not in logged
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in logged


class TestAStaleTimestampIsRejected:
    """spec: "A stale timestamp is rejected"."""

    def test_a_correctly_signed_stale_request_is_unauthenticated(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        status, _ = post_fixture(client, secret, "legal_drag", kind="stale")

        assert status == 401
        assert committer.calls == 0


class TestWebhookRedeliveryIsAReplay:
    """spec: "Webhook redelivery is a replay, not a second event"."""

    def test_the_redelivery_returns_the_original_result_marked_replayed(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        _, first = post_fixture(client, secret, "legal_drag")
        status, second = post_fixture(client, secret, "redelivery_duplicate")

        assert status == 200
        assert second["disposition"] == "replayed"
        assert second["replayed"] is True
        assert second["event_id"] == first["event_id"]

    def test_exactly_one_committer_effect(self, client: TestClient, secret: str, committer: RecordingCommitter) -> None:
        post_fixture(client, secret, "legal_drag")
        post_fixture(client, secret, "redelivery_duplicate")

        assert committer.calls == 2
        assert committer.effects == 1


class TestDispositionsThatWriteNothing:
    """Twenty's noise and the refusals: success, so Twenty stops asking, and no ledger write.

    The mapping decisions themselves are task 2.1's tests; what these assert is the route's half —
    the status code, the disposition body, and that nothing reached the committer.
    """

    @pytest.mark.parametrize(
        ("fixture", "reason"),
        [
            ("noop_create", "not_a_record_update"),
            ("noop_delete", "not_a_record_update"),
            ("noop_non_status_update", "status_field_untouched"),
            ("noop_unmapped_object", "unmapped_object"),
        ],
    )
    def test_a_non_drag_is_a_noop(
        self, client: TestClient, secret: str, committer: RecordingCommitter, fixture: str, reason: str
    ) -> None:
        status, body = post_fixture(client, secret, fixture)

        assert status == 200
        assert body == {"disposition": "noop", "reason": reason}
        assert committer.calls == 0

    def test_a_record_without_a_canonical_id_is_unmapped(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        status, body = post_fixture(client, secret, "missing_canonical_id")

        assert status == 200
        assert body["disposition"] == "unmapped"
        assert body["record_ref"] == f"patientProgram:{UNMAPPED_RECORD_ID}"
        assert committer.calls == 0

    def test_the_unmapped_log_line_names_the_record_and_board_only(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            post_fixture(client, secret, "missing_canonical_id")

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert UNMAPPED_RECORD_ID in logged
        assert "patientProgram.lifecycleStatus" in logged
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in logged

    def test_a_malformed_body_is_acknowledged_not_retried(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        """A body that does not parse will not parse on redelivery either, so a 5xx buys a retry storm."""
        status, body = post_fixture(client, secret, "malformed_body")

        assert status == 200
        assert body["disposition"] == "malformed"
        assert committer.calls == 0


class TestAnEchoOfTheStateOfRecordIsANoop:
    """spec: "An echo of the state of record is a noop" — no command, no note, one countable line.

    The mapping decision is `test_twenty_mapping.py`'s; what these assert is the threading — the
    route hands its injected state reader to the mapping, the echo comes back as a 200 noop with
    the new reason, and neither the committer nor the comment poster is touched.
    """

    @pytest.fixture
    def posts(self) -> list[tuple[str, str, str]]:
        return []

    @pytest.fixture
    def client(
        self, secret: str, committer: RecordingCommitter, posts: list[tuple[str, str, str]]
    ) -> Iterator[TestClient]:
        app = create_app(
            committer=committer,
            registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": secrets.token_urlsafe(32)}),
            twenty_webhook=TwentyWebhookConfig.from_env({
                TWENTY_WEBHOOK_ENABLED_ENV: "true",
                TWENTY_WEBHOOK_SECRET_ENV: secret,
            }),
            comment_poster=lambda card_ref, title, body: posts.append((card_ref, title, body)),
            # `legal_drag` targets ACTIVE, so a state of record of `active` makes it an echo.
            state_reader=lambda subject_type, subject_key: "active",
        )
        with TestClient(app) as test_client:
            yield test_client

    def test_an_echo_is_a_noop_with_the_echo_reason_and_commits_nothing(
        self, client: TestClient, secret: str, committer: RecordingCommitter
    ) -> None:
        status, body = post_fixture(client, secret, "legal_drag")

        assert status == 200
        assert body == {"disposition": "noop", "reason": "echo_of_record"}
        assert committer.calls == 0

    def test_an_echo_posts_no_comment(self, client: TestClient, secret: str, posts: list[tuple[str, str, str]]) -> None:
        post_fixture(client, secret, "legal_drag")

        assert posts == []

    def test_the_echo_log_line_carries_the_reason_and_no_payload_content(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            post_fixture(client, secret, "legal_drag")

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "disposition=noop" in logged
        assert "reason=echo_of_record" in logged
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in logged


class TestTheStructuredDispositionLog:
    """Every disposition is one countable log line carrying identifiers and codes only."""

    def test_a_commit_logs_route_disposition_subject_and_state(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO):
            post_fixture(client, secret, "legal_drag")

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert TWENTY_WEBHOOK_PATH in logged
        assert "disposition=committed" in logged
        assert FIXTURE_CANONICAL_ID in logged
        assert "to_state=active" in logged

    def test_no_disposition_logs_payload_content(
        self, client: TestClient, secret: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            for fixture in (
                "legal_drag",
                "redelivery_duplicate",
                "noop_create",
                "missing_canonical_id",
                "malformed_body",
            ):
                post_fixture(client, secret, fixture)

        logged = "\n".join(record.getMessage() for record in caplog.records)
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in logged
