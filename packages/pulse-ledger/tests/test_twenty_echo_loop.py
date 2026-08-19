"""Echo-loop termination proof (twenty-projection task 3.2, `twenty-heal-back` spec).

Task 3.1 tested each leg of the heal at its seam; what is under test here is the *loop* those legs
form through a live Twenty: a rejected drag heals the card, the heal PATCH fires Twenty's own
`patientProgram.updated` webhook straight back at the route, and without the mapping's
`echo_of_record` suppression that echo would map to a command, the catalog would refuse the
self-transition, and every rejection would spam its card with a note per bounce, forever
(falsified live 2026-08-18 — see the drag-command spec).

So the full bounce is driven end to end, socket-free: `illegal_drag` is delivered signed, the
route rejects and heals through the real `api_server.build_heal_writer` adapter over a recording
transport, and the echo delivery is *synthesized from the captured heal PATCH itself* — the PATCH
body's fields become `updatedFields` and the new `record` values, attributed the way Twenty stamps
an API-sourced write (`updatedBy.workspaceMemberId` null) — then signed and posted back through
signature verification and the mapping. Nothing about the echo is hand-invented except the server
stamp (`updatedAt`), which the PATCH does not carry because Twenty assigns it.

Termination is proven by counters, not absence of noise: across the whole bounce the committer is
reached exactly once (the original drag), the comment poster exactly once (the rejection note),
and the transport carries exactly one heal PATCH. The echo itself is a 200 `noop` with reason
`echo_of_record` — no command, no note, no second heal, so there is nothing left to fire a second
bounce (spec: "A heal write's echo is a noop").
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
from pulse_ledger.api import TWENTY_WEBHOOK_PATH, create_app
from pulse_ledger.auth import (
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    TwentyWebhookConfig,
)
from test_twenty_heal_back import (
    ENCODED_STATE_OF_RECORD,
    HEAL_PATCH_PATH,
    ILLEGAL_RECORD_ID,
    PROJECTION_TOKEN,
    TWENTY_BASE_URL,
)
from test_twenty_rejection_feedback import (
    FIXTURE_DEMOGRAPHICS,
    ILLEGAL_FROM_STATE,
    ILLEGAL_SUBJECT_TYPE,
    CatalogCommitter,
    RecordingCommentPoster,
)
from twenty_fixtures import SignatureKind, load_fixture_bytes, load_fixture_json, sign_fixture

#: The subject behind `illegal_drag.json`, in the ledger's vocabulary: the enrollment whose state
#: of record stays `active` because the backwards drag never committed.
ILLEGAL_CANONICAL_KEY = "DIM_PATIENT_CONFORMED-000102"

#: The server stamp Twenty would assign the heal write — after the drag's own `updatedAt`
#: (`2026-08-06T15:10:00.031Z`). It is the one echo field the captured PATCH cannot supply.
ECHO_UPDATED_AT = "2026-08-06T15:10:02.000Z"


class RecordingStateReader:
    """The route's state-of-record read: a constant answer, with every query recorded.

    The constant is the point — the illegal drag was rejected, so the ledger still holds
    `active` when the heal's echo arrives. Recording the queries proves the echo verdict came
    from consulting the ledger rather than from never reaching the mapping at all.
    """

    def __init__(self, state: str = ILLEGAL_FROM_STATE) -> None:
        self.state = state
        self.queries: list[tuple[str, str]] = []

    def __call__(self, subject_type: str, subject_key: str) -> str | None:
        self.queries.append((subject_type, subject_key))
        return self.state


class RecordingTwentyTransport:
    """The Twenty REST edge behind the real heal adapter: records every request, answers 200."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    @property
    def patches(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "PATCH"]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json={})

        return httpx.MockTransport(handle)


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
def state_reader() -> RecordingStateReader:
    return RecordingStateReader()


@pytest.fixture
def twenty_edge() -> RecordingTwentyTransport:
    return RecordingTwentyTransport()


@pytest.fixture
def client(
    secret: str,
    committer: CatalogCommitter,
    comment_poster: RecordingCommentPoster,
    state_reader: RecordingStateReader,
    twenty_edge: RecordingTwentyTransport,
) -> Iterator[TestClient]:
    """The route wired the way the running service is: the *built* heal writer, not a fake at the
    seam — the loop under proof runs through the same adapter production heals run through."""
    heal_writer = api_server.build_heal_writer(
        {
            api_server.PROJECTION_TWENTY_TOKEN_ENV: PROJECTION_TOKEN,
            api_server.TWENTY_BASE_URL_ENV: TWENTY_BASE_URL,
        },
        transport=twenty_edge.transport(),
    )
    assert heal_writer is not None
    app = create_app(
        committer=committer,
        comment_poster=comment_poster,
        heal_writer=heal_writer,
        state_reader=state_reader,
        registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": secrets.token_urlsafe(32)}),
        twenty_webhook=TwentyWebhookConfig.from_env({
            TWENTY_WEBHOOK_ENABLED_ENV: "true",
            TWENTY_WEBHOOK_SECRET_ENV: secret,
        }),
    )
    with TestClient(app) as test_client:
        yield test_client


def deliver(
    client: TestClient, secret: str, body: bytes, *, kind: SignatureKind = "valid"
) -> tuple[int, dict[str, object]]:
    """One webhook delivery as Twenty sends it: raw bytes, HMAC headers, the guarded route."""
    headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc), kind=kind)
    response = client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
    return response.status_code, response.json()


def echo_of(heal_patch: httpx.Request) -> bytes:
    """The `.updated` delivery Twenty fires for the heal write, built from the PATCH itself.

    The PATCH body's field names become `updatedFields` and its values land on the flat `record`
    — the same projection Twenty performs — over the record the card held when it was healed.
    `updatedBy` is the API-sourced shape (null `workspaceMemberId`): the mapping is documented to
    be unable to tell a projection write from a user's by attribution, so the echo must not
    smuggle in a discriminator the live webhook would not carry.
    """
    healed_fields = json.loads(heal_patch.content)
    record_id = heal_patch.url.path.rsplit("/", 1)[-1]
    assert record_id == ILLEGAL_RECORD_ID, "the heal must target the rejected drag's own card"
    original = load_fixture_json("illegal_drag")
    assert isinstance(original, dict)
    assert original["record"]["id"] == record_id
    record = {
        **original["record"],
        **healed_fields,
        "updatedAt": ECHO_UPDATED_AT,
        "updatedBy": {"source": "API", "workspaceMemberId": None, "name": "pulse-projection", "context": {}},
    }
    return json.dumps({**original, "record": record, "updatedFields": sorted(healed_fields)}).encode()


def drive_bounce(
    client: TestClient, secret: str, twenty_edge: RecordingTwentyTransport
) -> tuple[dict[str, object], dict[str, object]]:
    """The full loop: illegal drag in, rejection + heal out, the heal's echo back in.

    The asserts here are preconditions, not the scenario: a bounce that never rejected or never
    healed would make every downstream termination assertion vacuously green.
    """
    status, rejection = deliver(client, secret, load_fixture_bytes("illegal_drag"))
    assert status == 200
    assert rejection["disposition"] == "rejected", "the bounce must actually start with a rejection"
    assert len(twenty_edge.patches) == 1, "the rejection must actually have healed the card"
    status, echo = deliver(client, secret, echo_of(twenty_edge.patches[0]))
    assert status == 200
    return rejection, echo


class TestAHealWritesEchoIsANoop:
    """spec: "A heal write's echo is a noop" — the loop's exit, driven through the whole route."""

    def test_the_echo_terminates_as_an_echo_of_record(
        self, client: TestClient, secret: str, twenty_edge: RecordingTwentyTransport
    ) -> None:
        _, echo = drive_bounce(client, secret, twenty_edge)

        assert echo == {"disposition": "noop", "reason": "echo_of_record"}

    def test_no_command_is_submitted_for_the_echo(
        self,
        client: TestClient,
        secret: str,
        twenty_edge: RecordingTwentyTransport,
        committer: CatalogCommitter,
    ) -> None:
        """One committer call for the whole bounce — the original drag's — and zero events written."""
        drive_bounce(client, secret, twenty_edge)

        assert committer.calls == 1
        assert committer.effects == 0

    def test_no_note_is_posted_for_the_echo(
        self,
        client: TestClient,
        secret: str,
        twenty_edge: RecordingTwentyTransport,
        comment_poster: RecordingCommentPoster,
    ) -> None:
        """The rejection's own note is the bounce's only comment; the echo adds none.

        This is the live failure the suppression exists for: without it the echo mapped to a
        command, the catalog refused the self-transition, and a second note landed per heal.
        """
        drive_bounce(client, secret, twenty_edge)

        assert len(comment_poster.posts) == 1

    def test_the_echo_verdict_came_from_the_state_of_record(
        self,
        client: TestClient,
        secret: str,
        twenty_edge: RecordingTwentyTransport,
        state_reader: RecordingStateReader,
    ) -> None:
        """Both deliveries consult the ledger for the same subject; only the echo matches it."""
        drive_bounce(client, secret, twenty_edge)

        assert state_reader.queries == [(ILLEGAL_SUBJECT_TYPE, ILLEGAL_CANONICAL_KEY)] * 2


class TestExactlyOneHealPatchPerRejectionAcrossTheBounce:
    """The termination counter: the loop's one write, counted at the transport where it cannot lie."""

    def test_the_echo_triggers_no_second_heal(
        self, client: TestClient, secret: str, twenty_edge: RecordingTwentyTransport
    ) -> None:
        drive_bounce(client, secret, twenty_edge)

        assert len(twenty_edge.patches) == 1

    def test_the_one_heal_is_the_restoring_patch(
        self, client: TestClient, secret: str, twenty_edge: RecordingTwentyTransport
    ) -> None:
        """The counted write is the heal itself — the encoded state of record, on the right card."""
        drive_bounce(client, secret, twenty_edge)

        patch = twenty_edge.patches[0]
        assert patch.url.path == HEAL_PATCH_PATH
        assert json.loads(patch.content) == {"lifecycleStatus": ENCODED_STATE_OF_RECORD}

    def test_replaying_the_echo_still_heals_nothing(
        self,
        client: TestClient,
        secret: str,
        twenty_edge: RecordingTwentyTransport,
        committer: CatalogCommitter,
    ) -> None:
        """A redelivered echo — Twenty retries deliveries — terminates the same way every time."""
        drive_bounce(client, secret, twenty_edge)
        status, replayed = deliver(client, secret, echo_of(twenty_edge.patches[0]))

        assert status == 200
        assert replayed == {"disposition": "noop", "reason": "echo_of_record"}
        assert len(twenty_edge.patches) == 1
        assert committer.calls == 1


class TestTheEchoPassesTheSameDoorAsAnyDelivery:
    """The bounce runs through signature verification, not around it."""

    def test_a_tampered_echo_never_reaches_the_mapping(
        self,
        client: TestClient,
        secret: str,
        twenty_edge: RecordingTwentyTransport,
        state_reader: RecordingStateReader,
        committer: CatalogCommitter,
    ) -> None:
        drive_bounce(client, secret, twenty_edge)
        queries_after_bounce = len(state_reader.queries)
        status, _ = deliver(client, secret, echo_of(twenty_edge.patches[0]), kind="tampered")

        assert status == 401
        assert len(state_reader.queries) == queries_after_bounce
        assert committer.calls == 1


class TestTheBounceLeaksNoPayloadContent:
    """The route's PHI posture holds across the loop the echo adds — record fields stay out of logs."""

    def test_no_fixture_demographic_reaches_a_log_line_or_response(
        self,
        client: TestClient,
        secret: str,
        twenty_edge: RecordingTwentyTransport,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            rejection, echo = drive_bounce(client, secret, twenty_edge)

        swept = "\n".join([
            *(record.getMessage() for record in caplog.records),
            json.dumps([rejection, echo], default=str),
        ])
        assert "reason=echo_of_record" in swept, "the sweep must actually reach the echo path"
        for demographic in FIXTURE_DEMOGRAPHICS:
            assert demographic not in swept
