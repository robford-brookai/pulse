"""The command API's process wiring (task 4.5) — `pulse_ledger.api_server`.

No database and no `DATABASE_URL`: `create_app_from_env` is import-safe by construction (the
module docstring's whole point), so every test here builds against a fake pool whose
`.connection()` yields a sentinel object standing in for a real `psycopg.Connection`, the same
posture `test_api_auth.py` and `test_api_cursor.py` take with their fake committers and stores.
`--disable-socket` (the suite's default posture, `conftest.py`) never sees a socket attempt because
nothing here opens one: `ConnectionPool` itself is monkeypatched out before `create_app_from_env`
constructs it, and the Twenty comment adapter is only ever asked to build, never to send.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_ledger import api_server
from pulse_ledger.auth import WRITER_TOKEN_PREFIX
from pulse_ledger.commit import CommitResult, Declaration

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

# A synthetic subject key — not a patient identifier, not derived from one.
SUBJECT_KEY = "enrollment-0001"


class FakePool:
    """Stands in for `psycopg_pool.ConnectionPool`: `.connection()` yields one sentinel object.

    No real connection is ever opened, so this satisfies `--disable-socket` by construction.
    """

    def __init__(self) -> None:
        self.sentinel_conn = object()
        self.closed = False

    @contextmanager
    def connection(self) -> Iterator[object]:
        yield self.sentinel_conn

    def close(self) -> None:
        self.closed = True


def _declaration() -> Declaration:
    return Declaration(
        subject_type="enrollment",
        subject_key=SUBJECT_KEY,
        event_type="enrollment_started",
        to_state="received",
        effective_at=NOW,
        producer="test",
        actor_type="system",
        actor_id="test-writer",
    )


def _commit_result() -> CommitResult:
    return CommitResult(
        event_id=uuid.UUID(int=1),
        recorded_at=NOW,
        rule_version="v1",
        outbox_seq=1,
        state=None,
        replayed=False,
    )


class TestBuildCommitter:
    """`build_committer`'s fallthrough: a key routes to the idempotent path, its absence doesn't."""

    def test_a_present_key_routes_to_commit_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = FakePool()
        calls: list[tuple[object, ...]] = []
        result = _commit_result()

        def fake_commit_idempotent(conn: object, declaration: Declaration, *, idempotency_key: str) -> CommitResult:
            calls.append((conn, declaration, idempotency_key))
            return result

        def fail_commit_declaration(*_args: object, **_kwargs: object) -> CommitResult:  # pragma: no cover
            pytest.fail("commit_declaration must not be called when a key is present")

        monkeypatch.setattr(api_server, "commit_idempotent", fake_commit_idempotent)
        monkeypatch.setattr(api_server, "commit_declaration", fail_commit_declaration)

        committer = api_server.build_committer(pool)
        declaration = _declaration()
        assert committer(declaration, "idem-key-1") is result
        assert calls == [(pool.sentinel_conn, declaration, "idem-key-1")]

    def test_an_absent_key_routes_to_commit_declaration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = FakePool()
        calls: list[tuple[object, ...]] = []
        result = _commit_result()

        def fake_commit_declaration(conn: object, declaration: Declaration) -> CommitResult:
            calls.append((conn, declaration))
            return result

        def fail_commit_idempotent(*_args: object, **_kwargs: object) -> CommitResult:  # pragma: no cover
            pytest.fail("commit_idempotent must not be called when no key is present")

        monkeypatch.setattr(api_server, "commit_declaration", fake_commit_declaration)
        monkeypatch.setattr(api_server, "commit_idempotent", fail_commit_idempotent)

        committer = api_server.build_committer(pool)
        declaration = _declaration()
        assert committer(declaration, None) is result
        assert calls == [(pool.sentinel_conn, declaration)]


class TestBuildCursorReaderWriter:
    def test_reader_delegates_to_get_cursor_on_a_pooled_connection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = FakePool()
        calls: list[tuple[object, str]] = []

        def fake_get_cursor(conn: object, writer_id: str) -> None:
            calls.append((conn, writer_id))
            return None

        monkeypatch.setattr(api_server, "get_cursor", fake_get_cursor)
        reader = api_server.build_cursor_reader(pool)
        assert reader("verdict-relay") is None
        assert calls == [(pool.sentinel_conn, "verdict-relay")]

    def test_writer_delegates_to_put_cursor_on_a_pooled_connection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = FakePool()
        calls: list[tuple[object, str, dict[str, object]]] = []
        sentinel_cursor = object()

        def fake_put_cursor(conn: object, writer_id: str, cursor: dict[str, object]) -> object:
            calls.append((conn, writer_id, cursor))
            return sentinel_cursor

        monkeypatch.setattr(api_server, "put_cursor", fake_put_cursor)
        writer = api_server.build_cursor_writer(pool)
        assert writer("verdict-relay", {"batch": 4}) is sentinel_cursor
        assert calls == [(pool.sentinel_conn, "verdict-relay", {"batch": 4})]


class TestBuildStateReader:
    def test_reader_delegates_to_state_of_record_on_a_pooled_connection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pool = FakePool()
        calls: list[tuple[object, str, str]] = []

        def fake_state_of_record(conn: object, subject_type: str, subject_key: str) -> str:
            calls.append((conn, subject_type, subject_key))
            return "active"

        monkeypatch.setattr(api_server, "state_of_record", fake_state_of_record)
        reader = api_server.build_state_reader(pool)
        assert reader("enrollment", SUBJECT_KEY) == "active"
        assert calls == [(pool.sentinel_conn, "enrollment", SUBJECT_KEY)]


class TestBuildCommentPoster:
    """Left unwired when the token is absent — rejections still receipt (module docstring)."""

    def test_no_token_means_no_comment_poster(self) -> None:
        assert api_server.build_comment_poster({}) is None

    def test_token_without_a_base_url_also_stays_unwired(self) -> None:
        environ = {api_server.TWENTY_API_TOKEN_ENV: secrets.token_urlsafe(32)}
        assert api_server.build_comment_poster(environ) is None

    def test_token_and_base_url_build_a_bound_create_comment(self) -> None:
        environ = {
            api_server.TWENTY_API_TOKEN_ENV: secrets.token_urlsafe(32),
            api_server.TWENTY_BASE_URL_ENV: "https://twenty.example.test",
        }
        poster = api_server.build_comment_poster(environ)
        assert poster is not None
        assert poster.__self__.__class__.__name__ == "TwentyCommentClient"


class TestCreateAppFromEnv:
    """The factory itself: a real `DATABASE_URL` is never required, and `/health` needs no auth."""

    @pytest.fixture
    def relay_token(self) -> str:
        return secrets.token_urlsafe(32)

    @pytest.fixture
    def pool(self, monkeypatch: pytest.MonkeyPatch) -> FakePool:
        fake = FakePool()
        monkeypatch.setattr(api_server, "ConnectionPool", lambda *args, **kwargs: fake)
        return fake

    @pytest.fixture
    def app(self, pool: FakePool, relay_token: str) -> FastAPI:
        environ = {
            "DATABASE_URL": "postgresql://ignored-in-tests/ledger",
            f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": relay_token,
        }
        return api_server.create_app_from_env(environ)

    def test_health_returns_200_with_no_credential(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_is_not_behind_the_bearer_auth_error_handlers(self, app: FastAPI) -> None:
        # A malformed or missing Authorization header on /commands is 401; /health must never be.
        with TestClient(app) as client:
            commands_response = client.post("/commands", json={})
            health_response = client.get("/health")
        assert commands_response.status_code == 401
        assert health_response.status_code == 200

    def test_the_pool_is_closed_when_the_app_shuts_down(self, app: FastAPI, pool: FakePool) -> None:
        with TestClient(app) as client:
            client.get("/health")
            assert not pool.closed
        assert pool.closed
