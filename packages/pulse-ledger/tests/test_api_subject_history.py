"""The `/subjects/{subject_type}/{subject_key}/events` HTTP edge — auth, scope, and paging.

No database, same posture as `test_api_cursor.py`: the reader is a fake, because what is under
test is the boundary. `test_subject_history.py` owns the SQL against Postgres.

The scope call this route is held to (pulse-demo-closeout design decision 5): return committed
events for one subject, nothing more. So the suite asserts what it *refuses* as hard as what it
returns — an unauthenticated caller, an unknown credential, an unknown subject type — and that a
credential reaches this route on the same terms it reaches every other: authentication is the
whole authorization model the ledger has, and the projection reads under the credential it already
writes with.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator, Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pulse_core.history import subject_history_path
from pulse_ledger.api import HistoryStoreNotConfiguredError, create_app
from pulse_ledger.auth import WRITER_TOKEN_PREFIX, CredentialRegistry
from pulse_ledger.commit import CommitResult, Declaration
from pulse_ledger.validation import IllegalTransitionError


def _token() -> str:
    return secrets.token_urlsafe(32)


class _CommitPathUnexpectedlyReachedError(AssertionError):
    """A read route never reaches the commit path."""


class FailingCommitter:
    def __call__(self, declaration: Declaration, idempotency_key: str | None) -> CommitResult:  # pragma: no cover
        raise _CommitPathUnexpectedlyReachedError


def _envelope(seq: int, subject_key: str = "enr-1", to_state: str = "active") -> dict[str, object]:
    return {
        "event_id": f"00000000-0000-0000-0000-00000000000{seq}",
        "event_type": f"enrollment.{to_state}",
        "subject_type": "enrollment",
        "subject_key": subject_key,
        "seq": seq,
        "payload": {"to_state": to_state},
    }


class FakeHistory:
    """An in-memory ledger history, keyed by subject, that records how it was called."""

    def __init__(self, events: dict[tuple[str, str], list[dict[str, object]]]) -> None:
        self._events = events
        self.calls: list[tuple[str, str, int | None, int | None]] = []

    def read(
        self, subject_type: str, subject_key: str, *, after_seq: int | None, limit: int | None
    ) -> Sequence[dict[str, object]]:
        self.calls.append((subject_type, subject_key, after_seq, limit))
        if subject_type != "enrollment":
            raise IllegalTransitionError(subject_type, None, "", reason=f"unknown subject_type {subject_type!r}")
        rows = [
            row
            for row in self._events.get((subject_type, subject_key), [])
            if after_seq is None or row["seq"] > after_seq
        ]  # type: ignore[operator]
        return rows if limit is None else rows[:limit]


@pytest.fixture
def projection_token() -> str:
    return _token()


@pytest.fixture
def registry(projection_token: str) -> CredentialRegistry:
    return CredentialRegistry.from_env({f"{WRITER_TOKEN_PREFIX}TWENTY_PROJECTION": projection_token})


@pytest.fixture
def history() -> FakeHistory:
    return FakeHistory({
        ("enrollment", "enr-1"): [_envelope(1, to_state="pending_start"), _envelope(2), _envelope(3, to_state="ended")],
        ("enrollment", "enr-2"): [_envelope(1, subject_key="enr-2", to_state="pending_start")],
    })


@pytest.fixture
def app(registry: CredentialRegistry, history: FakeHistory) -> FastAPI:
    return create_app(committer=FailingCommitter(), registry=registry, history_reader=history.read)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the route returns a subject's events in sequence -------------------------------------------


def test_the_route_returns_the_subjects_events_in_ledger_sequence(client: TestClient, projection_token: str) -> None:
    response = client.get(subject_history_path("enrollment", "enr-1"), headers=_auth(projection_token))

    assert response.status_code == 200
    body = response.json()
    assert body["subject_type"] == "enrollment"
    assert body["subject_key"] == "enr-1"
    assert body["count"] == 3
    assert [event["seq"] for event in body["events"]] == [1, 2, 3]


def test_the_route_returns_one_subjects_events_and_no_others(client: TestClient, projection_token: str) -> None:
    body = client.get(subject_history_path("enrollment", "enr-2"), headers=_auth(projection_token)).json()

    assert {event["subject_key"] for event in body["events"]} == {"enr-2"}


def test_an_unknown_subject_is_an_empty_history_not_a_404(client: TestClient, projection_token: str) -> None:
    response = client.get(subject_history_path("enrollment", "enr-nobody"), headers=_auth(projection_token))

    assert response.status_code == 200
    assert response.json() == {
        "subject_type": "enrollment",
        "subject_key": "enr-nobody",
        "count": 0,
        "events": [],
    }


def test_an_unknown_subject_type_is_rejected_with_the_catalogs_reason(
    client: TestClient, projection_token: str
) -> None:
    response = client.get(subject_history_path("enrolment", "enr-1"), headers=_auth(projection_token))

    assert response.status_code == 422
    assert "enrolment" in response.json()["detail"]["message"]


@pytest.mark.parametrize("subject_key", ["enr 1", "enr+1", "enr%1", "enr#1", "enr?1", "enr&1"])
def test_a_subject_key_with_reserved_characters_reaches_the_reader_intact(
    client: TestClient, projection_token: str, history: FakeHistory, subject_key: str
) -> None:
    """A subject key is opaque to everything but the producer that minted it. `subject_history_path`
    percent-encodes it so a `?` or a `#` addresses the subject rather than starting a query string
    or a fragment — the failure mode where a caller silently reads a *different* subject's history."""
    client.get(subject_history_path("enrollment", subject_key), headers=_auth(projection_token))

    assert history.calls[-1][:2] == ("enrollment", subject_key)


# --- refusal ------------------------------------------------------------------------------------


def test_a_request_with_no_credential_is_refused(client: TestClient, history: FakeHistory) -> None:
    response = client.get(subject_history_path("enrollment", "enr-1"))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert history.calls == []


def test_a_credential_no_writer_owns_is_refused(client: TestClient, history: FakeHistory) -> None:
    response = client.get(subject_history_path("enrollment", "enr-1"), headers=_auth(_token()))

    assert response.status_code == 401
    assert history.calls == []


def test_a_malformed_authorization_header_is_refused(client: TestClient, history: FakeHistory) -> None:
    response = client.get(subject_history_path("enrollment", "enr-1"), headers={"Authorization": _token()})

    assert response.status_code == 401
    assert history.calls == []


def test_the_route_is_read_only(client: TestClient, projection_token: str) -> None:
    """No verb but GET reaches it — a replay surface that accepted a write would be a second door
    into the ledger, past every attribution rule `/commands` enforces."""
    path = subject_history_path("enrollment", "enr-1")
    for verb in (client.post, client.put, client.patch, client.delete):
        assert verb(path, headers=_auth(projection_token)).status_code == 405


def test_a_refusal_names_no_credential_value(client: TestClient, projection_token: str) -> None:
    response = client.get(subject_history_path("enrollment", "enr-1"), headers=_auth(_token()))

    assert projection_token not in response.text


# --- paging -------------------------------------------------------------------------------------


def test_after_seq_and_limit_reach_the_reader(client: TestClient, projection_token: str, history: FakeHistory) -> None:
    body = client.get(
        subject_history_path("enrollment", "enr-1"),
        params={"after_seq": 1, "limit": 1},
        headers=_auth(projection_token),
    ).json()

    assert history.calls[-1] == ("enrollment", "enr-1", 1, 1)
    assert [event["seq"] for event in body["events"]] == [2]


def test_a_page_size_over_the_cap_is_clamped_not_refused(
    client: TestClient, projection_token: str, history: FakeHistory
) -> None:
    from pulse_core.history import MAX_HISTORY_PAGE_SIZE

    response = client.get(
        subject_history_path("enrollment", "enr-1"),
        params={"limit": MAX_HISTORY_PAGE_SIZE * 10},
        headers=_auth(projection_token),
    )

    assert response.status_code == 200
    assert history.calls[-1][3] == MAX_HISTORY_PAGE_SIZE


def test_a_negative_page_size_is_refused(client: TestClient, projection_token: str) -> None:
    response = client.get(
        subject_history_path("enrollment", "enr-1"),
        params={"limit": -1},
        headers=_auth(projection_token),
    )

    assert response.status_code == 422


def test_no_page_size_asks_the_reader_for_the_default(
    client: TestClient, projection_token: str, history: FakeHistory
) -> None:
    from pulse_core.history import DEFAULT_HISTORY_PAGE_SIZE

    client.get(subject_history_path("enrollment", "enr-1"), headers=_auth(projection_token))

    assert history.calls[-1] == ("enrollment", "enr-1", None, DEFAULT_HISTORY_PAGE_SIZE)


# --- wiring -------------------------------------------------------------------------------------


def test_an_app_with_no_history_store_fails_only_when_the_route_is_hit(
    registry: CredentialRegistry, projection_token: str
) -> None:
    app = create_app(committer=FailingCommitter(), registry=registry)
    with TestClient(app) as client, pytest.raises(HistoryStoreNotConfiguredError):
        client.get(subject_history_path("enrollment", "enr-1"), headers=_auth(projection_token))
