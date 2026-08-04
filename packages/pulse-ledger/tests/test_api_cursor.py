"""The `/writers/{writer_id}/cursor` HTTP edge — auth, attribution, and the crash/resume round-trip.

No database here, same posture as `test_api_auth.py`: the store is a fake dict, because what is
under test is the auth boundary (only a writer's own cursor, ever) and the request/response shape.
`test_cursor.py` owns the real store against Postgres.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_ledger.api import WRITER_CURSOR_PATH, CursorStoreNotConfiguredError, create_app
from pulse_ledger.auth import WRITER_AUTHORITY_PREFIX, WRITER_TOKEN_PREFIX, CredentialRegistry
from pulse_ledger.commit import CommitResult, Declaration
from pulse_ledger.cursor import WriterCursor

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _token() -> str:
    return secrets.token_urlsafe(32)


class _CommitPathUnexpectedlyReachedError(AssertionError):
    """The cursor routes never reach the commit path."""


class FailingCommitter:
    def __call__(
        self, declaration: Declaration, idempotency_key: str | None
    ) -> CommitResult:  # pragma: no cover - unused here
        raise _CommitPathUnexpectedlyReachedError


class FakeCursorStore:
    """An in-memory `ledger.writer_state`, for testing the HTTP edge without a database."""

    def __init__(self) -> None:
        self._rows: dict[str, WriterCursor] = {}

    def read(self, writer_id: str) -> WriterCursor | None:
        return self._rows.get(writer_id)

    def write(self, writer_id: str, cursor: dict[str, object]) -> WriterCursor:
        stored = WriterCursor(writer_id=writer_id, cursor=cursor, updated_at=NOW)
        self._rows[writer_id] = stored
        return stored


@pytest.fixture
def relay_token() -> str:
    return _token()


@pytest.fixture
def scheduler_token() -> str:
    return _token()


@pytest.fixture
def registry(relay_token: str, scheduler_token: str) -> CredentialRegistry:
    return CredentialRegistry.from_env({
        f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": relay_token,
        f"{WRITER_AUTHORITY_PREFIX}VERDICT_RELAY": "verdict-publication",
        f"{WRITER_TOKEN_PREFIX}SCHEDULER": scheduler_token,
    })


@pytest.fixture
def store() -> FakeCursorStore:
    return FakeCursorStore()


@pytest.fixture
def app(registry: CredentialRegistry, store: FakeCursorStore) -> FastAPI:
    return create_app(
        committer=FailingCommitter(),
        registry=registry,
        cursor_reader=store.read,
        cursor_writer=store.write,
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def path(writer_id: str) -> str:
    return WRITER_CURSOR_PATH.format(writer_id=writer_id)


class TestCrashAndResume:
    """The ledger-read spec scenario, driven through the HTTP edge."""

    def test_put_then_get_returns_the_persisted_cursor(self, client: TestClient, relay_token: str) -> None:
        put_response = client.put(
            path("verdict-relay"),
            json={"batch": 4, "computed_at": "2026-08-03T00:00:00+00:00"},
            headers=auth(relay_token),
        )
        assert put_response.status_code == 200, put_response.text

        get_response = client.get(path("verdict-relay"), headers=auth(relay_token))
        assert get_response.status_code == 200, get_response.text
        assert get_response.json()["cursor"] == {"batch": 4, "computed_at": "2026-08-03T00:00:00+00:00"}
        assert get_response.json()["writer_id"] == "verdict-relay"

    def test_a_writer_with_no_persisted_cursor_gets_404(self, client: TestClient, relay_token: str) -> None:
        response = client.get(path("verdict-relay"), headers=auth(relay_token))
        assert response.status_code == 404

    def test_a_later_checkpoint_replaces_the_earlier_one(self, client: TestClient, relay_token: str) -> None:
        client.put(path("verdict-relay"), json={"batch": 4}, headers=auth(relay_token))
        client.put(path("verdict-relay"), json={"batch": 5}, headers=auth(relay_token))

        response = client.get(path("verdict-relay"), headers=auth(relay_token))
        assert response.json()["cursor"] == {"batch": 5}


class TestAuthentication:
    def test_no_credential_is_401_on_get(self, client: TestClient) -> None:
        assert client.get(path("verdict-relay")).status_code == 401

    def test_no_credential_is_401_on_put(self, client: TestClient) -> None:
        assert client.put(path("verdict-relay"), json={"batch": 1}).status_code == 401

    def test_an_unknown_credential_is_401(self, client: TestClient) -> None:
        assert client.get(path("verdict-relay"), headers=auth(_token())).status_code == 401


class TestWriterIsolation:
    """A writer may read or write only its own cursor (D15) — never another writer's."""

    def test_a_writer_cannot_read_another_writers_cursor(
        self, client: TestClient, relay_token: str, scheduler_token: str
    ) -> None:
        client.put(path("scheduler"), json={"batch": 9}, headers=auth(scheduler_token))

        response = client.get(path("scheduler"), headers=auth(relay_token))

        assert response.status_code == 403
        assert response.json()["detail"]["field"] == "writer_id"
        assert response.json()["detail"]["writer_id"] == "verdict-relay"
        assert response.json()["detail"]["claimed"] == "scheduler"

    def test_a_writer_cannot_write_another_writers_cursor(
        self, client: TestClient, relay_token: str, store: FakeCursorStore
    ) -> None:
        response = client.put(path("scheduler"), json={"batch": 1}, headers=auth(relay_token))

        assert response.status_code == 403
        assert store.read("scheduler") is None


class TestBodyValidation:
    def test_a_non_object_body_is_422(self, client: TestClient, relay_token: str) -> None:
        response = client.put(path("verdict-relay"), json=["not", "an", "object"], headers=auth(relay_token))
        assert response.status_code == 422

    def test_a_body_that_is_not_json_is_422(self, client: TestClient, relay_token: str) -> None:
        response = client.put(path("verdict-relay"), content=b"not json", headers=auth(relay_token))
        assert response.status_code == 422

    def test_a_non_json_native_value_is_422(self, client: TestClient, relay_token: str) -> None:
        # `float("inf")` has no compliant JSON spelling, so the body is built as raw bytes using
        # the non-standard `Infinity` literal Python's own `json.loads` accepts on decode — the
        # value the API boundary must still catch and reject.
        response = client.put(path("verdict-relay"), content=b'{"batch": Infinity}', headers=auth(relay_token))
        assert response.status_code == 422


class TestUnconfiguredStore:
    def test_an_app_built_without_a_cursor_store_raises_only_when_the_route_is_hit(
        self, registry: CredentialRegistry, relay_token: str
    ) -> None:
        app = create_app(committer=FailingCommitter(), registry=registry)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(path("verdict-relay"), headers=auth(relay_token))
        assert response.status_code == 500

    def test_the_unconfigured_default_also_covers_writes(self, registry: CredentialRegistry, relay_token: str) -> None:
        app = create_app(committer=FailingCommitter(), registry=registry)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.put(path("verdict-relay"), json={"batch": 1}, headers=auth(relay_token))
        assert response.status_code == 500

    def test_the_error_names_what_is_missing(self) -> None:
        with pytest.raises(CursorStoreNotConfiguredError):
            raise CursorStoreNotConfiguredError()
