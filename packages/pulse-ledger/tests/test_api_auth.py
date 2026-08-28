"""The auth boundary at the HTTP edge: who you are decides what the event says you are.

No database here — the commit path is a fake, because what is under test is everything that
happens before it and what never reaches it. Task 3.2's suite owns the transaction.
"""

from __future__ import annotations

import dataclasses
import logging
import secrets
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_ledger.api import (
    COMMANDS_BATCH_PATH,
    COMMANDS_PATH,
    TWENTY_WEBHOOK_PATH,
    coerce_declaration_fields,
    create_app,
)
from pulse_ledger.auth import (
    BACKFILL_ACTOR_ID,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    TWENTY_WEBHOOK_SECRET_NEXT_ENV,
    WRITER_AUTHORITY_PREFIX,
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    NoCredentialsConfiguredError,
    TwentyWebhookConfig,
    sign,
)
from pulse_ledger.commit import CommitResult, Declaration
from pulse_ledger.fold import FoldedState
from pulse_ledger.validation import IllegalTransitionError

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)

# A synthetic subject key. Not a patient identifier and not derived from one.
SUBJECT_KEY = "enrollment-0001"


def _token() -> str:
    return secrets.token_urlsafe(32)


_EVENT_ID_BASE = uuid.UUID("018f5a1e-0000-7000-8000-000000000000").int


class FakeCommitter:
    """Records what reached the commit path — including that nothing did.

    Mirrors `commit_idempotent`'s replay contract: a repeated key returns the original commit's
    result with `replayed=True` and no new event id, so the HTTP edge can be tested end to end
    without the database `test_idempotent_commit.py` already covers.
    """

    def __init__(self, raises: Exception | None = None) -> None:
        self.declarations: list[Declaration] = []
        self.keys: list[str | None] = []
        self.raises = raises
        self._by_key: dict[str, CommitResult] = {}

    def __call__(self, declaration: Declaration, idempotency_key: str | None) -> CommitResult:
        self.declarations.append(declaration)
        self.keys.append(idempotency_key)
        if self.raises is not None:
            raise self.raises
        if idempotency_key is not None and idempotency_key in self._by_key:
            return dataclasses.replace(self._by_key[idempotency_key], replayed=True)
        event_id = uuid.UUID(int=_EVENT_ID_BASE + len(self.declarations))
        result = CommitResult(
            event_id=event_id,
            recorded_at=NOW,
            rule_version="appendix-c-v0.7",
            outbox_seq=len(self.declarations),
            state=FoldedState(
                state="on_hold",
                effective_at=NOW,
                recorded_at=NOW,
                event_id=event_id,
            ),
        )
        if idempotency_key is not None:
            self._by_key[idempotency_key] = result
        return result

    @property
    def called(self) -> bool:
        return bool(self.declarations)


@pytest.fixture
def relay_token() -> str:
    return _token()


@pytest.fixture
def backfill_token() -> str:
    return _token()


@pytest.fixture
def registry(relay_token: str, backfill_token: str) -> CredentialRegistry:
    return CredentialRegistry.from_env({
        f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": relay_token,
        f"{WRITER_AUTHORITY_PREFIX}VERDICT_RELAY": "verdict-publication",
        f"{WRITER_TOKEN_PREFIX}SCHEDULER": _token(),
        f"{WRITER_TOKEN_PREFIX}BACKFILL": backfill_token,
    })


@pytest.fixture
def committer() -> FakeCommitter:
    return FakeCommitter()


@pytest.fixture
def app(registry: CredentialRegistry, committer: FakeCommitter) -> FastAPI:
    return create_app(committer=committer, registry=registry, twenty_webhook=TwentyWebhookConfig())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def declaration_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_type": "enrollment",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_transition",
        "to_state": "on_hold",
        "effective_at": "2026-08-03T11:59:00+00:00",
        "payload": {"hold_reason": "awaiting_authorization"},
    }
    body.update(overrides)
    return body


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestBearerAuthentication:
    def test_no_credential_is_401(self, client: TestClient, committer: FakeCommitter) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body())
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert not committer.called

    def test_a_malformed_header_is_401(self, client: TestClient, committer: FakeCommitter) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(), headers={"Authorization": "Basic nope"})
        assert response.status_code == 401
        assert not committer.called

    def test_an_unknown_credential_is_401(self, client: TestClient, committer: FakeCommitter) -> None:
        presented = _token()
        response = client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(presented))
        assert response.status_code == 401
        assert presented not in response.text
        assert not committer.called

    def test_a_known_credential_commits(self, client: TestClient, relay_token: str) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        assert response.status_code == 201, response.text
        assert response.json()["event_id"] == "018f5a1e-0000-7000-8000-000000000001"
        assert response.json()["rule_version"] == "appendix-c-v0.7"
        assert response.json()["state"]["state"] == "on_hold"


class TestAttribution:
    def test_the_actor_is_the_credentials_writer(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        declared = committer.declarations[0]
        assert declared.actor_id == "verdict-relay"
        assert declared.actor_type == "system"
        assert declared.actor_authority == "verdict-publication"
        assert declared.producer == "verdict-relay"

    def test_the_boundary_parses_the_timestamp(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        assert committer.declarations[0].effective_at == datetime(2026, 8, 3, 11, 59, tzinfo=timezone.utc)

    def test_the_occurred_at_alias_is_accepted(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        body = declaration_body()
        body["occurred_at"] = body.pop("effective_at")
        response = client.post(COMMANDS_PATH, json=body, headers=auth(relay_token))
        assert response.status_code == 201, response.text
        assert committer.declarations[0].effective_at == datetime(2026, 8, 3, 11, 59, tzinfo=timezone.utc)

    def test_a_z_suffixed_timestamp_is_accepted(self, client: TestClient, relay_token: str) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(effective_at="2026-08-03T11:59:00Z"), headers=auth(relay_token)
        )
        assert response.status_code == 201, response.text

    def test_a_naive_timestamp_is_rejected(self, client: TestClient, relay_token: str) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(effective_at="2026-08-03T11:59:00"), headers=auth(relay_token)
        )
        assert response.status_code == 422

    def test_an_unparseable_timestamp_is_rejected(self, client: TestClient, relay_token: str) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(effective_at="yesterday"), headers=auth(relay_token)
        )
        assert response.status_code == 422

    def test_correlation_ids_are_parsed(self, client: TestClient, relay_token: str, committer: FakeCommitter) -> None:
        correlation = uuid.uuid4()
        client.post(COMMANDS_PATH, json=declaration_body(correlation_id=str(correlation)), headers=auth(relay_token))
        assert committer.declarations[0].correlation_id == correlation


class TestSpoofing:
    """The command-api spec's scenario, at the boundary that decides it."""

    def test_a_writer_cannot_declare_as_another_actor(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(actor_id="reconciliation"), headers=auth(relay_token)
        )
        assert response.status_code == 403
        assert not committer.called
        assert response.json()["detail"]["field"] == "actor_id"
        assert response.json()["detail"]["writer_id"] == "verdict-relay"

    @pytest.mark.parametrize("field", ["actor_type", "actor_id", "actor_authority", "producer"])
    def test_no_credential_derived_field_may_come_from_the_body(
        self, client: TestClient, relay_token: str, committer: FakeCommitter, field: str
    ) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(**{field: "reconciliation"}), headers=auth(relay_token)
        )
        assert response.status_code == 403
        assert not committer.called

    def test_a_server_set_field_is_refused(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(rule_version="forged-v9"), headers=auth(relay_token)
        )
        assert response.status_code == 422
        assert not committer.called

    def test_an_unknown_field_is_refused_rather_than_dropped(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(nonsense="x"), headers=auth(relay_token))
        assert response.status_code == 422
        assert not committer.called


class TestBoundaryCoercion:
    """JSON has no datetimes and no UUIDs; `Declaration` has both, and this is where they meet."""

    def test_evidence_bounds_arrive_as_a_pair_of_instants(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(
            COMMANDS_PATH,
            json=declaration_body(evidence_bounds=["2026-08-01T00:00:00+00:00", "2026-08-03T00:00:00+00:00"]),
            headers=auth(relay_token),
        )
        assert response.status_code == 201, response.text
        assert committer.declarations[0].evidence_bounds == (
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 3, tzinfo=timezone.utc),
        )

    def test_an_unbounded_evidence_window_is_left_alone(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(evidence_bounds=None), headers=auth(relay_token))
        assert response.status_code == 201, response.text
        assert committer.declarations[0].evidence_bounds is None

    @pytest.mark.parametrize("value", [17, {"nested": "object"}])
    def test_a_non_string_timestamp_is_422(self, client: TestClient, relay_token: str, value: object) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(effective_at=value), headers=auth(relay_token))
        assert response.status_code == 422

    @pytest.mark.parametrize("value", ["not-a-uuid", 17])
    def test_a_bad_correlation_id_is_422(self, client: TestClient, relay_token: str, value: object) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(correlation_id=value), headers=auth(relay_token))
        assert response.status_code == 422

    def test_a_committer_result_without_state_serialises(self, registry: CredentialRegistry, relay_token: str) -> None:
        """A reversal can leave a subject stateless; the response says so rather than omitting it."""
        stateless = CommitResult(
            event_id=uuid.uuid4(), recorded_at=NOW, rule_version="appendix-c-v0.7", outbox_seq=2, state=None
        )
        app = create_app(
            committer=lambda _declaration, _key: stateless, registry=registry, twenty_webhook=TwentyWebhookConfig()
        )
        with TestClient(app) as client:
            response = client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        assert response.status_code == 201, response.text
        assert response.json()["state"] is None

    def test_already_typed_values_pass_through(self) -> None:
        """The coercion is called directly by the batch path (3.5) too, where types may be real."""
        correlation = uuid.uuid4()
        coerced = coerce_declaration_fields({"effective_at": NOW, "correlation_id": correlation})
        assert coerced == {"effective_at": NOW, "correlation_id": correlation}


class TestRejectionSurface:
    def test_body_that_is_not_json_is_422(self, client: TestClient, relay_token: str) -> None:
        response = client.post(COMMANDS_PATH, content=b"not json at all", headers=auth(relay_token))
        assert response.status_code == 422

    def test_an_illegal_transition_carries_reason_and_catalog_version(
        self, registry: CredentialRegistry, relay_token: str
    ) -> None:
        error = IllegalTransitionError("enrollment", "withdrawn", "on_hold", reason="no such transition")
        app = create_app(committer=FakeCommitter(raises=error), registry=registry, twenty_webhook=TwentyWebhookConfig())
        with TestClient(app) as client:
            response = client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["reason"] == "no such transition"
        assert detail["catalog_version"] == error.catalog_version
        assert detail["from_state"] == "withdrawn"

    def test_a_missing_effective_at_is_422(self, client: TestClient, relay_token: str) -> None:
        body = declaration_body()
        del body["effective_at"]
        assert client.post(COMMANDS_PATH, json=body, headers=auth(relay_token)).status_code == 422

    def test_a_non_object_body_is_422(self, client: TestClient, relay_token: str) -> None:
        assert client.post(COMMANDS_PATH, json=["not", "an", "object"], headers=auth(relay_token)).status_code == 422


class TestLogHygiene:
    """A rejection is exactly when something gets logged, so it is exactly where a leak lands."""

    def test_a_rejected_command_logs_no_credential_and_no_payload(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        presented = _token()
        with caplog.at_level(logging.DEBUG):
            client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(presented))
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert presented not in logged
        assert "awaiting_authorization" not in logged

    def test_a_spoof_logs_the_writer_but_not_the_payload(
        self, client: TestClient, relay_token: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            client.post(COMMANDS_PATH, json=declaration_body(actor_id="reconciliation"), headers=auth(relay_token))
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "verdict-relay" in logged
        assert relay_token not in logged
        assert "awaiting_authorization" not in logged


class TestTwentyWebhookRoute:
    """D8's kanban ingress: the middleware ships, the route ships off (roadmap Phase 2)."""

    secret = _token()

    def test_the_route_does_not_exist_by_default(self, client: TestClient) -> None:
        assert client.post(TWENTY_WEBHOOK_PATH, json={}).status_code == 404

    def test_default_config_from_env_leaves_it_off(self, registry: CredentialRegistry) -> None:
        app = create_app(committer=FakeCommitter(), registry=registry, twenty_webhook=TwentyWebhookConfig.from_env({}))
        with TestClient(app) as client:
            assert client.post(TWENTY_WEBHOOK_PATH, json={}).status_code == 404

    @pytest.fixture
    def signed_client(self, registry: CredentialRegistry) -> Iterator[TestClient]:
        app = create_app(
            committer=FakeCommitter(),
            registry=registry,
            twenty_webhook=TwentyWebhookConfig.from_env({
                TWENTY_WEBHOOK_ENABLED_ENV: "true",
                TWENTY_WEBHOOK_SECRET_ENV: self.secret,
            }),
        )
        with TestClient(app) as client:
            yield client

    def test_enabled_it_rejects_an_unsigned_request(self, signed_client: TestClient) -> None:
        response = signed_client.post(TWENTY_WEBHOOK_PATH, content=b"{}")
        assert response.status_code == 401
        # The signed route does not challenge for a bearer token it would not accept.
        assert response.headers["WWW-Authenticate"].startswith("Signature")

    def test_enabled_it_rejects_a_bad_signature(self, signed_client: TestClient) -> None:
        timestamp = str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))
        response = signed_client.post(
            TWENTY_WEBHOOK_PATH,
            content=b"{}",
            headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: "v1=" + "0" * 64},
        )
        assert response.status_code == 401

    def test_enabled_it_rejects_a_stale_signature(self, signed_client: TestClient) -> None:
        stale = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        timestamp = str(int(stale.timestamp() * 1000))
        response = signed_client.post(
            TWENTY_WEBHOOK_PATH,
            content=b"{}",
            headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(self.secret, timestamp, b"{}")},
        )
        assert response.status_code == 401

    def test_a_valid_signature_reaches_the_handler(self, signed_client: TestClient) -> None:
        """Authenticated and interpreted: a body that is not a Twenty drag is an acknowledged no-op.

        What this suite owns is that the door opened; `test_twenty_webhook_route.py` owns what is
        behind it.
        """
        body = b'{"card":"synthetic"}'
        timestamp = str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))
        response = signed_client.post(
            TWENTY_WEBHOOK_PATH,
            content=body,
            headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(self.secret, timestamp, body)},
        )
        assert response.status_code == 200
        assert response.json()["disposition"] == "noop"

    def test_the_webhook_route_takes_no_bearer_credential(self, signed_client: TestClient, relay_token: str) -> None:
        """A writer credential must not open the webhook door, and vice versa."""
        assert signed_client.post(TWENTY_WEBHOOK_PATH, content=b"{}", headers=auth(relay_token)).status_code == 401


class TestTwentyWebhookRotationOverHttp:
    """The rotation window as the route sees it (D15 quarterly cadence)."""

    retired = _token()
    incoming = _token()

    @staticmethod
    def _post(client: TestClient, secret: str) -> int:
        body = b'{"card":"synthetic"}'
        timestamp = str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))
        response = client.post(
            TWENTY_WEBHOOK_PATH,
            content=body,
            headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(secret, timestamp, body)},
        )
        return response.status_code

    @staticmethod
    def _client(registry: CredentialRegistry, env: dict[str, str]) -> TestClient:
        app = create_app(
            committer=FakeCommitter(),
            registry=registry,
            twenty_webhook=TwentyWebhookConfig.from_env({TWENTY_WEBHOOK_ENABLED_ENV: "true", **env}),
        )
        return TestClient(app)

    def test_both_secrets_reach_the_route_during_rotation(self, registry: CredentialRegistry) -> None:
        env = {TWENTY_WEBHOOK_SECRET_ENV: self.retired, TWENTY_WEBHOOK_SECRET_NEXT_ENV: self.incoming}
        with self._client(registry, env) as client:
            assert self._post(client, self.retired) == 200
            assert self._post(client, self.incoming) == 200

    def test_the_retired_secret_is_unauthenticated_once_removed(self, registry: CredentialRegistry) -> None:
        with self._client(registry, {TWENTY_WEBHOOK_SECRET_ENV: self.incoming}) as client:
            assert self._post(client, self.incoming) == 200
            assert self._post(client, self.retired) == 401


class TestIdempotency:
    """DNA-801: the D16 key crosses the HTTP boundary and `replayed` comes back.

    The key is accepted-if-present — a keyless body still commits. `commit_idempotent`'s own
    replay semantics are covered against Postgres by `test_idempotent_commit.py`; here the
    committer is a fake and what is under test is the boundary's extraction and echo.
    """

    KEY = "verdict-relay:0123456789abcdef"

    def test_a_body_carrying_an_idempotency_key_commits(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(idempotency_key=self.KEY), headers=auth(relay_token)
        )
        assert response.status_code == 201, response.text
        assert committer.keys == [self.KEY]
        assert response.json()["replayed"] is False

    def test_a_repeated_key_replays_the_original_commit(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        body = declaration_body(idempotency_key=self.KEY)
        first = client.post(COMMANDS_PATH, json=body, headers=auth(relay_token))
        second = client.post(COMMANDS_PATH, json=body, headers=auth(relay_token))
        assert first.json()["replayed"] is False
        assert second.status_code == 201, second.text
        assert second.json()["replayed"] is True
        assert second.json()["event_id"] == first.json()["event_id"]

    def test_a_keyless_body_still_commits(self, client: TestClient, relay_token: str, committer: FakeCommitter) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        assert response.status_code == 201, response.text
        assert committer.keys == [None]
        assert response.json()["replayed"] is False

    def test_a_non_string_key_is_422(self, client: TestClient, relay_token: str, committer: FakeCommitter) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(idempotency_key=17), headers=auth(relay_token))
        assert response.status_code == 422
        assert not committer.called

    def test_a_batch_passes_each_items_key_through(
        self, client: TestClient, backfill_token: str, committer: FakeCommitter
    ) -> None:
        body = [
            declaration_body(
                subject_key=f"{SUBJECT_KEY}-{index}",
                event_type="reconstruction_gap",
                idempotency_key=f"backfill:{index}",
            )
            for index in range(2)
        ]
        response = client.post(COMMANDS_BATCH_PATH, json=body, headers=auth(backfill_token))
        assert response.status_code == 201, response.text
        assert committer.keys == ["backfill:0", "backfill:1"]
        assert [item["replayed"] for item in response.json()] == [False, False]


class TestBackfillMode:
    """Task 3.5: `backfill_genesis` and `reconstruction_gap` are restricted to the backfill actor."""

    @pytest.mark.parametrize("event_type", ["backfill_genesis", "reconstruction_gap"])
    def test_a_forward_writer_is_rejected_on_a_backfill_only_event_type(
        self, client: TestClient, relay_token: str, committer: FakeCommitter, event_type: str
    ) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(event_type=event_type), headers=auth(relay_token))
        assert response.status_code == 403
        assert not committer.called
        assert response.json()["detail"]["event_type"] == event_type
        assert response.json()["detail"]["writer_id"] == "verdict-relay"

    @pytest.mark.parametrize("event_type", ["backfill_genesis", "reconstruction_gap"])
    def test_the_backfill_actor_may_declare_a_backfill_only_event_type(
        self, client: TestClient, backfill_token: str, committer: FakeCommitter, event_type: str
    ) -> None:
        response = client.post(
            COMMANDS_PATH, json=declaration_body(event_type=event_type), headers=auth(backfill_token)
        )
        assert response.status_code == 201, response.text
        assert committer.declarations[0].actor_id == BACKFILL_ACTOR_ID

    def test_an_ordinary_event_type_is_unrestricted(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(), headers=auth(relay_token))
        assert response.status_code == 201, response.text
        assert committer.called


class TestCommandsBatch:
    """`POST /commands:batch` (task 3.5): one credential, an array of commands, same validation."""

    def _batch_body(self, count: int = 2) -> list[dict[str, object]]:
        return [
            declaration_body(subject_key=f"{SUBJECT_KEY}-{index}", event_type="reconstruction_gap")
            for index in range(count)
        ]

    def test_a_batch_commits_every_item_in_order(
        self, client: TestClient, backfill_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(COMMANDS_BATCH_PATH, json=self._batch_body(2), headers=auth(backfill_token))
        assert response.status_code == 201, response.text
        assert len(response.json()) == 2
        assert [d.subject_key for d in committer.declarations] == [f"{SUBJECT_KEY}-0", f"{SUBJECT_KEY}-1"]

    def test_a_non_array_batch_body_is_422(self, client: TestClient, backfill_token: str) -> None:
        response = client.post(COMMANDS_BATCH_PATH, json={"not": "an array"}, headers=auth(backfill_token))
        assert response.status_code == 422

    def test_a_forward_writer_is_rejected_on_a_batch_of_backfill_only_commands(
        self, client: TestClient, relay_token: str, committer: FakeCommitter
    ) -> None:
        response = client.post(COMMANDS_BATCH_PATH, json=self._batch_body(2), headers=auth(relay_token))
        assert response.status_code == 403
        assert not committer.called

    def test_a_bad_item_aborts_the_whole_batch_before_any_of_it_commits(
        self, client: TestClient, backfill_token: str, committer: FakeCommitter
    ) -> None:
        body = [*self._batch_body(1), declaration_body(event_type="reconstruction_gap", nonsense="x")]
        response = client.post(COMMANDS_BATCH_PATH, json=body, headers=auth(backfill_token))
        assert response.status_code == 422
        assert not committer.called


class TestBoot:
    def test_the_app_refuses_to_boot_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in list(dict(__import__("os").environ)):
            if name.startswith(WRITER_TOKEN_PREFIX):
                monkeypatch.delenv(name, raising=False)
        with pytest.raises(NoCredentialsConfiguredError):
            create_app(committer=FakeCommitter())
