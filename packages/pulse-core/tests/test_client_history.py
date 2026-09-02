"""`PulseCoreClient.subject_history` — the read half of the client contract (decision 5).

`httpx.MockTransport` fakes the API boundary, same posture as `test_client.py`: no live network.
What is under test is the client's own behaviour — that it pages to exhaustion, that it retries a
transient answer and not a rejection, and that a refusal raises rather than returning an empty
history a caller would rebuild a projection from.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pulse_core.client import PulseCoreClient, SubjectHistoryRefusedError
from pulse_core.history import DEFAULT_HISTORY_PAGE_SIZE, subject_history_path

TOKEN = "x" * 40


def _events(*seqs: int) -> list[dict[str, object]]:
    return [{"event_id": f"e{seq}", "subject_type": "enrollment", "subject_key": "enr-1", "seq": seq} for seq in seqs]


def _page(*seqs: int) -> httpx.Response:
    events = _events(*seqs)
    return httpx.Response(
        200,
        json={"subject_type": "enrollment", "subject_key": "enr-1", "count": len(events), "events": events},
    )


def _client(handler: object, **kwargs: object) -> PulseCoreClient:
    return PulseCoreClient(
        "http://ledger.invalid",
        writer_id="twenty-projection",
        token=TOKEN,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=lambda seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_single_page_history_comes_back_in_order() -> None:
    with _client(lambda request: _page(1, 2, 3)) as client:
        history = client.subject_history("enrollment", "enr-1")

    assert [event["seq"] for event in history] == [1, 2, 3]


def test_the_request_names_the_subject_and_carries_the_credential() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _page()

    with _client(handler) as client:
        client.subject_history("enrollment", "enr-1")

    assert seen[0].url.path == subject_history_path("enrollment", "enr-1")
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert seen[0].url.params["limit"] == str(DEFAULT_HISTORY_PAGE_SIZE)
    assert "after_seq" not in seen[0].url.params


def test_a_full_page_is_followed_by_a_request_for_the_next() -> None:
    """A page the size of the limit may not be the end. Stopping there would hand a rebuild a
    truncated history — which folds cleanly, and to the wrong state."""
    pages = [_page(1, 2), _page(3, 4), _page(5)]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return pages[len(seen) - 1]

    with _client(handler) as client:
        history = client.subject_history("enrollment", "enr-1", page_size=2)

    assert [event["seq"] for event in history] == [1, 2, 3, 4, 5]
    assert [request.url.params.get("after_seq") for request in seen] == [None, "2", "4"]


def test_a_short_page_ends_the_walk() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _page(1)

    with _client(handler) as client:
        client.subject_history("enrollment", "enr-1", page_size=2)

    assert len(seen) == 1


def test_an_empty_history_is_an_answer_not_an_error() -> None:
    with _client(lambda request: _page()) as client:
        assert client.subject_history("enrollment", "enr-nobody") == []


@pytest.mark.parametrize("status", [401, 403, 422])
def test_a_refusal_raises_rather_than_reading_as_an_empty_history(status: int) -> None:
    with (
        _client(lambda request: httpx.Response(status, json={"detail": "nope"})) as client,
        pytest.raises(SubjectHistoryRefusedError) as excinfo,
    ):
        client.subject_history("enrollment", "enr-1")

    assert excinfo.value.status_code == status


def test_a_refusal_names_no_credential_value() -> None:
    with (
        _client(lambda request: httpx.Response(401, json={"detail": "nope"})) as client,
        pytest.raises(SubjectHistoryRefusedError) as excinfo,
    ):
        client.subject_history("enrollment", "enr-1")

    assert TOKEN not in str(excinfo.value)


def test_a_transient_answer_is_retried_then_succeeds() -> None:
    responses = [httpx.Response(503), _page(1)]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    with _client(handler) as client:
        assert [event["seq"] for event in client.subject_history("enrollment", "enr-1")] == [1]


def test_transient_answers_stop_at_max_attempts() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    with _client(handler, max_attempts=3) as client, pytest.raises(SubjectHistoryRefusedError):
        client.subject_history("enrollment", "enr-1")

    assert attempts == 3


def test_a_body_that_is_not_a_history_is_refused_rather_than_folded() -> None:
    with (
        _client(lambda request: httpx.Response(200, content=b"not json")) as client,
        pytest.raises(SubjectHistoryRefusedError),
    ):
        client.subject_history("enrollment", "enr-1")

    with (
        _client(lambda request: httpx.Response(200, json={"events": "nope"})) as client,
        pytest.raises(SubjectHistoryRefusedError),
    ):
        client.subject_history("enrollment", "enr-1")


def test_a_page_whose_last_event_has_no_seq_stops_rather_than_looping() -> None:
    """Without a `seq` there is no cursor for the next page, and asking again with the same
    `after_seq` would loop forever."""
    body = json.loads(_page(1, 2).content)
    body["events"][-1].pop("seq")

    with _client(lambda request: httpx.Response(200, json=body)) as client, pytest.raises(SubjectHistoryRefusedError):
        client.subject_history("enrollment", "enr-1", page_size=2)
