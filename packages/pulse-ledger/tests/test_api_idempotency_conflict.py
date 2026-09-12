"""Idempotency conflicts at every ingress, and what a client makes of them — task 3.1.

The ledger side of the D16 amendment already decides *whether* a key may be replayed
(`test_idempotency_binding.py`, `test_legacy_idempotency_binding.py`). What is under test here is
the other half: how `IdempotencyConflictError` reaches a caller through each of the three ingresses,
and that it reaches each of them as a refusal rather than as something worth retrying.

The three mappings are deliberately different shapes, for reasons the change's design decision 3
gives:

- **`POST /commands`** answers 409 with the coded reason — a status an SDK can classify.
- **`POST /commands:batch`** keeps its envelope and its per-item transaction policy: the array
  still comes back 201 with one entry per item, and a conflicting item is a rejected entry in its
  own position while its neighbours commit.
- **`POST /webhooks/twenty`** keeps 200 with a rejected disposition, because Twenty reads
  2xx/non-2xx and a 4xx past the door buys redelivery forever rather than a message anyone reads.

Two properties are asserted on every one of them:

- **Nothing of the prior request escapes.** Not the original event id, not its result, not the
  fingerprint, not the writer of record — a conflict response must not be usable to probe what a
  key already holds. The assertions are made against the whole rendered response body, so a field
  added later has to be excluded deliberately.
- **A valid retry keeps its success shape.** The compatibility criterion for this change is that
  existing correct producers see no change at all, so the replay path is asserted beside the
  conflict path rather than assumed.

Most of this runs against a fake committer, which is the boundary these routes are tested at
everywhere else. `TestConflictOverARealLedger` is the end-to-end proof on a real Postgres: a real
`commit_idempotent` behind a real app, so the 409 is produced by an actual binding mismatch and the
"no second event" claim is a row count rather than a fake's promise.
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_core.client import (
    PulseCoreClient,
    ResponseClassification,
    classify_response,
)
from pulse_core.generated import DeclareTransitionCommand
from pulse_ledger.api import (
    COMMANDS_BATCH_PATH,
    COMMANDS_PATH,
    DISPOSITION_REJECTED,
    TWENTY_WEBHOOK_PATH,
    create_app,
)
from pulse_ledger.auth import (
    WRITER_TOKEN_PREFIX,
    CredentialRegistry,
    TwentyWebhookConfig,
    Writer,
)
from pulse_ledger.commit import CommitResult, Declaration, commit_declaration
from pulse_ledger.fold import FoldedState
from pulse_ledger.idempotency import (
    IDEMPOTENCY_CONFLICT,
    IDEMPOTENCY_LEGACY_UNVERIFIABLE,
    IdempotencyConflictError,
    commit_idempotent,
)
from twenty_fixtures import load_fixture_bytes, sign_fixture

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)

#: A synthetic subject key. Not a patient identifier and not derived from one.
SUBJECT_KEY = "enrollment-0001"

KEY = "verdict-relay:9f2c0c1a"

#: The facts a conflict response must never carry. `PRIOR_EVENT_ID` and `PRIOR_FINGERPRINT` are what
#: the key already holds; a response mentioning either would let a caller probe the ledger with
#: guessed keys.
PRIOR_EVENT_ID = str(uuid.UUID(int=0x0189_0000_0000_7000_8000_000000000001))
PRIOR_FINGERPRINT = "v1:aa11bb22"
PRIOR_WRITER_ID = "reconciliation"


def _token() -> str:
    return secrets.token_urlsafe(32)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ConflictingCommitter:
    """A commit path that refuses the nth key it is given, and commits everything else.

    The refusal is a real `IdempotencyConflictError`, raised the way `commit_idempotent` raises it:
    the key, the coded reason, and nothing else on the exception. Which call conflicts is chosen by
    the test, so a batch can be given one bad item among good ones without the fake needing to
    understand bindings.
    """

    def __init__(self, *, conflict_on: set[int] | None = None, reason: str = IDEMPOTENCY_CONFLICT) -> None:
        self.declarations: list[Declaration] = []
        self.keys: list[str | None] = []
        self._conflict_on = {0} if conflict_on is None else conflict_on
        self._reason = reason
        self._by_key: dict[str, CommitResult] = {}

    @property
    def calls(self) -> int:
        return len(self.declarations)

    def __call__(self, declaration: Declaration, idempotency_key: str | None) -> CommitResult:
        index = len(self.declarations)
        self.declarations.append(declaration)
        self.keys.append(idempotency_key)
        if index in self._conflict_on:
            raise IdempotencyConflictError(idempotency_key or "", reason=self._reason)
        if idempotency_key is not None and idempotency_key in self._by_key:
            stored = self._by_key[idempotency_key]
            return CommitResult(
                event_id=stored.event_id,
                recorded_at=stored.recorded_at,
                rule_version=stored.rule_version,
                outbox_seq=stored.outbox_seq,
                state=stored.state,
                replayed=True,
            )
        event_id = uuid.UUID(int=0x0189_0000_0000_7000_8000_000000000100 + index)
        result = CommitResult(
            event_id=event_id,
            recorded_at=NOW,
            rule_version="appendix-c-v0.7",
            outbox_seq=index + 1,
            state=FoldedState(state="on_hold", effective_at=NOW, recorded_at=NOW, event_id=event_id),
        )
        if idempotency_key is not None:
            self._by_key[idempotency_key] = result
        return result


def declaration_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_type": "enrollment",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_transition",
        "to_state": "on_hold",
        "effective_at": NOW.isoformat(),
    }
    body.update(overrides)
    return body


def assert_discloses_nothing(rendered: str) -> None:
    """No part of what the key already holds may appear in a refusal.

    Asserted against the rendered body rather than field by field: a response that grows a field
    carrying the prior commit fails here without the test having to anticipate its name.
    """
    for secret_fact in (PRIOR_EVENT_ID, PRIOR_FINGERPRINT, PRIOR_WRITER_ID, "fingerprint", "outbox_seq"):
        assert secret_fact not in rendered, rendered


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
        f"{WRITER_TOKEN_PREFIX}BACKFILL": backfill_token,
    })


@contextmanager
def build_client(registry: CredentialRegistry, committer: ConflictingCommitter) -> Iterator[TestClient]:
    """An app at the HTTP edge over one fake commit path — the boundary every route suite uses."""
    app = create_app(committer=committer, registry=registry, twenty_webhook=TwentyWebhookConfig())
    with TestClient(app) as test_client:
        yield test_client


class TestSingleCommandConflict:
    """spec: "Mismatched key reuse is rejected" — the HTTP half of it."""

    @pytest.fixture
    def committer(self) -> ConflictingCommitter:
        return ConflictingCommitter()

    @pytest.fixture
    def client(self, registry: CredentialRegistry, committer: ConflictingCommitter) -> Iterator[TestClient]:
        with build_client(registry, committer) as test_client:
            yield test_client

    def test_a_conflicting_key_is_409_with_the_coded_reason(self, client: TestClient, relay_token: str) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(idempotency_key=KEY), headers=auth(relay_token))

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["reason"] == IDEMPOTENCY_CONFLICT

    def test_the_refusal_discloses_nothing_about_the_original(self, client: TestClient, relay_token: str) -> None:
        response = client.post(COMMANDS_PATH, json=declaration_body(idempotency_key=KEY), headers=auth(relay_token))

        assert_discloses_nothing(response.text)
        assert "event_id" not in response.json()

    def test_the_refusal_does_not_echo_the_key_or_the_request(self, client: TestClient, relay_token: str) -> None:
        """The key names a writer, and the body will carry PHI once C1 clears. Neither is feedback."""
        response = client.post(COMMANDS_PATH, json=declaration_body(idempotency_key=KEY), headers=auth(relay_token))

        assert KEY not in response.text
        assert SUBJECT_KEY not in response.text

    def test_a_legacy_unverifiable_key_keeps_its_own_reason(
        self, registry: CredentialRegistry, relay_token: str
    ) -> None:
        """spec: "Unverifiable legacy retry blocks unsafe rollout" — a distinct code, same status."""
        committer = ConflictingCommitter(reason=IDEMPOTENCY_LEGACY_UNVERIFIABLE)
        with build_client(registry, committer) as client:
            response = client.post(COMMANDS_PATH, json=declaration_body(idempotency_key=KEY), headers=auth(relay_token))

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["reason"] == IDEMPOTENCY_LEGACY_UNVERIFIABLE

    def test_a_valid_retry_keeps_its_success_shape(self, registry: CredentialRegistry, relay_token: str) -> None:
        """spec: "Retry after timeout is a replay" — the compatibility criterion, unchanged."""
        committer = ConflictingCommitter(conflict_on=set())
        body = declaration_body(idempotency_key=KEY)
        with build_client(registry, committer) as client:
            first = client.post(COMMANDS_PATH, json=body, headers=auth(relay_token))
            second = client.post(COMMANDS_PATH, json=body, headers=auth(relay_token))

        assert (first.status_code, second.status_code) == (201, 201), second.text
        assert second.json()["replayed"] is True
        assert second.json()["event_id"] == first.json()["event_id"]


class TestBatchConflict:
    """spec: "Batch and Twenty conflicts do not cause transient retries" — the batch half."""

    def _batch_body(self, count: int) -> list[dict[str, object]]:
        return [
            declaration_body(
                subject_key=f"{SUBJECT_KEY}-{index}",
                event_type="reconstruction_gap",
                idempotency_key=f"backfill:{index}",
            )
            for index in range(count)
        ]

    def _post(
        self, registry: CredentialRegistry, token: str, committer: ConflictingCommitter, count: int
    ) -> httpx.Response:
        with build_client(registry, committer) as client:
            return client.post(COMMANDS_BATCH_PATH, json=self._batch_body(count), headers=auth(token))

    def test_the_envelope_is_unchanged_and_the_conflict_is_one_items_result(
        self, registry: CredentialRegistry, backfill_token: str
    ) -> None:
        committer = ConflictingCommitter(conflict_on={1})
        response = self._post(registry, backfill_token, committer, 3)

        assert response.status_code == 201, response.text
        items = response.json()
        assert len(items) == 3
        assert items[1] == {"disposition": DISPOSITION_REJECTED, "reason": IDEMPOTENCY_CONFLICT}

    def test_a_conflicting_item_does_not_stop_its_neighbours(
        self, registry: CredentialRegistry, backfill_token: str
    ) -> None:
        """The per-item transaction policy the batch already had: each item is its own commit."""
        committer = ConflictingCommitter(conflict_on={1})
        response = self._post(registry, backfill_token, committer, 3)

        items = response.json()
        assert [item.get("replayed") for item in items] == [False, None, False]
        assert committer.calls == 3

    def test_a_committed_item_keeps_its_success_shape(self, registry: CredentialRegistry, backfill_token: str) -> None:
        committer = ConflictingCommitter(conflict_on={1})
        response = self._post(registry, backfill_token, committer, 3)

        first = response.json()[0]
        assert set(first) == {"event_id", "recorded_at", "rule_version", "outbox_seq", "state", "replayed"}

    def test_the_conflicting_item_discloses_nothing(self, registry: CredentialRegistry, backfill_token: str) -> None:
        committer = ConflictingCommitter(conflict_on={1})
        response = self._post(registry, backfill_token, committer, 3)

        assert_discloses_nothing(json.dumps(response.json()[1]))


class TestTwentyWebhookConflict:
    """spec: "Batch and Twenty conflicts do not cause transient retries" — the signed-ingress half."""

    @pytest.fixture
    def secret(self) -> str:
        return _token()

    def _deliver(self, secret: str, committer: ConflictingCommitter) -> httpx.Response:
        app = create_app(
            committer=committer,
            registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": _token()}),
            twenty_webhook=TwentyWebhookConfig(enabled=True, secret=secret),
        )
        body = load_fixture_bytes("legal_drag")
        headers = sign_fixture(secret, body, now=datetime.now(tz=timezone.utc))
        with TestClient(app) as client:
            return client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)

    def test_a_conflict_is_200_with_a_rejected_disposition(self, secret: str) -> None:
        """200, because Twenty reads 2xx/non-2xx: a 4xx here is a redelivery instruction."""
        response = self._deliver(secret, ConflictingCommitter())

        assert response.status_code == 200, response.text
        assert response.json()["disposition"] == DISPOSITION_REJECTED
        assert response.json()["reason"] == IDEMPOTENCY_CONFLICT

    def test_a_conflict_is_not_the_handler_failure_path(self, secret: str) -> None:
        """A conflict is a verdict. Answering 500 would have Twenty redeliver it forever."""
        response = self._deliver(secret, ConflictingCommitter())

        assert response.status_code != 500
        assert "error" not in response.text

    def test_the_receipt_discloses_nothing_about_the_original(self, secret: str) -> None:
        response = self._deliver(secret, ConflictingCommitter())

        assert_discloses_nothing(response.text)
        assert "event_id" not in response.json()

    def test_a_legacy_unverifiable_conflict_keeps_its_own_reason(self, secret: str) -> None:
        response = self._deliver(secret, ConflictingCommitter(reason=IDEMPOTENCY_LEGACY_UNVERIFIABLE))

        assert response.status_code == 200, response.text
        assert response.json()["reason"] == IDEMPOTENCY_LEGACY_UNVERIFIABLE


class TestSdkClassification:
    """spec: "SDK clients SHALL classify idempotency conflicts as rejected rather than transient"."""

    def _conflict_response(self, reason: str = IDEMPOTENCY_CONFLICT) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": {"message": "idempotency key is claimed by another request", "reason": reason}},
            request=httpx.Request("POST", "http://ledger.test/commands"),
        )

    def test_a_409_classifies_as_rejected(self) -> None:
        result = classify_response(self._conflict_response())

        assert result.classification is ResponseClassification.REJECTED
        assert result.is_success is False

    def test_the_coded_reason_survives_classification(self) -> None:
        assert classify_response(self._conflict_response()).rejection is not None
        assert classify_response(self._conflict_response()).rejection.reason == IDEMPOTENCY_CONFLICT  # type: ignore[union-attr]

    def test_a_legacy_unverifiable_conflict_is_rejected_too(self) -> None:
        result = classify_response(self._conflict_response(IDEMPOTENCY_LEGACY_UNVERIFIABLE))

        assert result.classification is ResponseClassification.REJECTED
        assert result.rejection is not None
        assert result.rejection.reason == IDEMPOTENCY_LEGACY_UNVERIFIABLE

    def test_a_conflict_is_answered_once_and_never_retried(self) -> None:
        """The retry-storm acceptance: a conflict costs exactly one request, whatever the budget."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return self._conflict_response()

        with PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
            max_attempts=4,
        ) as client:
            result = client.submit_command(
                DeclareTransitionCommand(subject_key="enr-1", subject_type="enrollment", to_state="on_hold"),
                effective_at=NOW,
            )

        assert result.classification is ResponseClassification.REJECTED
        assert attempts == 1
        assert result.attempts == 1


# --- end to end, over a real ledger -------------------------------------------------------------


RELAY = Writer(writer_id="verdict-relay")
OTHER = Writer(writer_id="reconciliation")


def _bound_committer(conn: psycopg.Connection, writer: Writer) -> Any:
    """A committer that binds its writer — what the enforce stage wires in, one writer at a time.

    The running service still wires `api_server.build_committer`, which passes no writer at all:
    binding enforcement is a later stage of this change's rollout (design decision 5), and this
    task is the ingress mapping that has to be deployed before it. So the two writers below are two
    apps rather than one app resolving each token to its own writer — what is under test is the
    ledger's conflict travelling out through HTTP, not the wiring that will eventually produce it.
    """

    def committer(declaration: Declaration, idempotency_key: str | None) -> CommitResult:
        if idempotency_key is None:
            return commit_declaration(conn, declaration)
        return commit_idempotent(conn, declaration, idempotency_key=idempotency_key, writer=writer)

    return committer


def _app_for(conn: psycopg.Connection, writer: Writer, token: str) -> FastAPI:
    env_suffix = writer.writer_id.upper().replace("-", "_")
    return create_app(
        committer=_bound_committer(conn, writer),
        registry=CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}{env_suffix}": token}),
        twenty_webhook=TwentyWebhookConfig(),
    )


def _referral_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "subject_type": "referral",
        "subject_key": "ref-0001",
        "event_type": "referral.received",
        "to_state": "received",
        "effective_at": NOW.isoformat(),
    }
    body.update(overrides)
    return body


class TestConflictOverARealLedger:
    """The 409 produced by an actual binding mismatch, and the row counts behind it.

    Everything above proves the mapping. This proves there is something to map: a real
    `commit_idempotent` on a migrated database, reached through the real app, with the ledger's own
    tables asserted afterwards.
    """

    KEY = "verdict-relay:1a2b3c4d"

    @pytest.fixture
    def relay_client(self, ledger_db: psycopg.Connection) -> Iterator[TestClient]:
        token = _token()
        with TestClient(_app_for(ledger_db, RELAY, token)) as client:
            client.headers.update(auth(token))
            yield client

    @pytest.fixture
    def other_client(self, ledger_db: psycopg.Connection) -> Iterator[TestClient]:
        token = _token()
        with TestClient(_app_for(ledger_db, OTHER, token)) as client:
            client.headers.update(auth(token))
            yield client

    def _events(self, conn: psycopg.Connection) -> int:
        return int(conn.execute("SELECT count(*) FROM ledger.events").fetchone()[0])  # type: ignore[index]

    def test_another_writer_reusing_the_key_is_409_and_writes_nothing(
        self, ledger_db: psycopg.Connection, relay_client: TestClient, other_client: TestClient
    ) -> None:
        committed = relay_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))
        assert committed.status_code == 201, committed.text

        conflict = other_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))

        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["detail"]["reason"] == IDEMPOTENCY_CONFLICT
        assert self._events(ledger_db) == 1

    def test_the_cross_writer_refusal_leaks_no_part_of_the_original(
        self, relay_client: TestClient, other_client: TestClient
    ) -> None:
        committed = relay_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))
        original_event_id = committed.json()["event_id"]

        conflict = other_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))

        assert original_event_id not in conflict.text
        assert "fingerprint" not in conflict.text
        assert RELAY.writer_id not in conflict.text

    def test_the_same_writer_changing_the_request_is_409(
        self, ledger_db: psycopg.Connection, relay_client: TestClient
    ) -> None:
        relay_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))

        conflict = relay_client.post(
            COMMANDS_PATH,
            json=_referral_body(idempotency_key=self.KEY, subject_key="ref-0002"),
        )

        assert conflict.status_code == 409, conflict.text
        assert self._events(ledger_db) == 1

    def test_the_same_writers_exact_retry_still_replays(
        self, ledger_db: psycopg.Connection, relay_client: TestClient
    ) -> None:
        """The compatibility criterion, over the real path: a correct producer sees no change."""
        first = relay_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))
        second = relay_client.post(COMMANDS_PATH, json=_referral_body(idempotency_key=self.KEY))

        assert second.status_code == 201, second.text
        assert second.json()["replayed"] is True
        assert second.json()["event_id"] == first.json()["event_id"]
        assert self._events(ledger_db) == 1
