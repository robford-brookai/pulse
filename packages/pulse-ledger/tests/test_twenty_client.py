"""The outbound Twenty comment adapter (twenty-kanban-webhook-ingress task 2.2, design decision 6).

Everything runs at the HTTP boundary against `httpx.MockTransport` — no socket is ever opened, and
an autouse fixture enforces that rather than trusting a command-line flag. The PHI scans use the
recognizable fake demographics from the 1.1 fixtures (`Canary`, case last names): a comment body or
error message is clean only if none of them appear.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import pytest_socket
from pulse_ledger.twenty.client import (
    COMMENTS_PATH,
    TWENTY_API_TOKEN_ENV,
    CommentPostError,
    RejectionReceipt,
    TwentyApiTokenMissingError,
    TwentyCommentClient,
    format_rejection_comment,
)
from twenty_fixtures import load_fixture_json

BASE_URL = "https://twenty.example.test"
#: Long enough to be a plausible credential; recognizable so a leak scan can grep for it.
TOKEN = "twenty-api-token-canary-0123456789abcdef"  # noqa: S105 — synthetic test credential

CARD_REF = "twenty-record-patientprogram-0002"

RECEIPT = RejectionReceipt(
    card_ref=CARD_REF,
    from_state="activated",
    to_state="registered",
    reason="transition_not_permitted",
    catalog_version="1.0.0",
)


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """No adapter test may open a socket — the boundary is `httpx.MockTransport`, full stop."""
    pytest_socket.disable_socket()
    yield
    pytest_socket.enable_socket()


def _demographic_strings() -> list[str]:
    """Every payload-derived string from the illegal-drag fixture that must never leave the process."""
    payload = load_fixture_json("illegal_drag")
    assert isinstance(payload, dict)
    record = payload["record"]
    return [
        record["name"],
        record["updatedBy"]["name"],
        record["canonicalPatientId"],
        record["patientId"],
    ]


def _recording_client(
    responses: list[httpx.Response | Exception],
    requests: list[httpx.Request],
    **kwargs: object,
) -> TwentyCommentClient:
    """A client whose transport replays `responses` in order (repeating the last) into `requests`."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        result = responses[min(len(requests), len(responses)) - 1]
        if isinstance(result, Exception):
            raise result
        return result

    return TwentyCommentClient(
        BASE_URL,
        token=TOKEN,
        transport=httpx.MockTransport(handler),
        **kwargs,  # type: ignore[arg-type]
    )


# --- format_rejection_comment: receipt fields only, never payload content ---


def test_comment_names_transition_reason_catalog_and_unchanged_state() -> None:
    body = format_rejection_comment(RECEIPT)
    assert "activated" in body
    assert "registered" in body
    assert "transition_not_permitted" in body
    assert "1.0.0" in body
    assert "state of record is unchanged" in body


def test_comment_carries_no_demographic_or_payload_field() -> None:
    body = format_rejection_comment(RECEIPT)
    for leaked in _demographic_strings():
        assert leaked not in body


def test_comment_formats_a_first_declaration_with_no_from_state() -> None:
    receipt = RejectionReceipt(
        card_ref=CARD_REF,
        from_state=None,
        to_state="registered",
        reason="unknown subject_type",
        catalog_version="1.0.0",
    )
    body = format_rejection_comment(receipt)
    assert "no prior state" in body
    assert "registered" in body
    assert "state of record is unchanged" in body


# --- posting: one call, card ref + receipt body, bearer credential ---


def test_posting_invokes_the_adapter_once_with_card_ref_and_receipt_body() -> None:
    requests: list[httpx.Request] = []
    client = _recording_client([httpx.Response(201, json={"id": "comment-0001"})], requests)
    body = format_rejection_comment(RECEIPT)

    client.create_comment(CARD_REF, body)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == COMMENTS_PATH
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    wire = json.loads(request.content)
    assert wire["cardRef"] == CARD_REF
    assert wire["body"] == body
    assert "activated" in wire["body"]
    assert "registered" in wire["body"]
    assert "transition_not_permitted" in wire["body"]
    for leaked in _demographic_strings():
        assert leaked not in wire["body"]


# --- retry: bounded backoff on 5xx/timeouts, permanent failure is typed and names the card only ---


def test_5xx_retries_with_backoff_then_raises_naming_the_card_ref_only() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    client = _recording_client(
        [httpx.Response(503, text="upstream unavailable")],
        requests,
        max_attempts=3,
        sleep=sleeps.append,
    )

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, format_rejection_comment(RECEIPT))

    assert len(requests) == 3
    assert sleeps == [0.5, 1.0]  # exponential from the base delay, one sleep between attempts
    error = excinfo.value
    assert error.card_ref == CARD_REF
    assert error.attempts == 3
    assert error.status_code == 503
    assert CARD_REF in str(error)
    for leaked in (TOKEN, *_demographic_strings()):
        assert leaked not in str(error)
        assert leaked not in repr(error)


def test_timeout_retries_then_succeeds() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    client = _recording_client(
        [
            httpx.ConnectTimeout("connection timed out"),
            httpx.ReadTimeout("read timed out"),
            httpx.Response(201, json={"id": "comment-0002"}),
        ],
        requests,
        sleep=sleeps.append,
    )

    client.create_comment(CARD_REF, format_rejection_comment(RECEIPT))

    assert len(requests) == 3
    assert len(sleeps) == 2


def test_exhausted_timeouts_raise_with_no_status_code() -> None:
    requests: list[httpx.Request] = []
    client = _recording_client(
        [httpx.ConnectTimeout("connection timed out")],
        requests,
        max_attempts=2,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, format_rejection_comment(RECEIPT))

    assert len(requests) == 2
    assert excinfo.value.status_code is None
    assert CARD_REF in str(excinfo.value)


def test_4xx_is_permanent_with_no_retry() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    client = _recording_client([httpx.Response(404, text="no such object")], requests, sleep=sleeps.append)

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, format_rejection_comment(RECEIPT))

    assert len(requests) == 1
    assert sleeps == []
    assert excinfo.value.status_code == 404
    assert excinfo.value.attempts == 1


# --- the credential never appears in any error or log line ---


def test_credential_never_appears_in_errors_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    requests: list[httpx.Request] = []
    client = _recording_client(
        [httpx.Response(500, text="boom")],
        requests,
        max_attempts=2,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, format_rejection_comment(RECEIPT))

    assert TOKEN not in caplog.text
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)
    for record in caplog.records:
        assert TOKEN not in record.getMessage()


# --- configuration: the token comes from the environment and its absence fails loud ---


def test_from_env_builds_a_client_with_the_configured_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "comment-0003"})

    client = TwentyCommentClient.from_env(
        {TWENTY_API_TOKEN_ENV: TOKEN},
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    client.create_comment(CARD_REF, format_rejection_comment(RECEIPT))
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_from_env_refuses_a_missing_token() -> None:
    with pytest.raises(TwentyApiTokenMissingError):
        TwentyCommentClient.from_env({}, base_url=BASE_URL)


def test_from_env_refuses_a_blank_token() -> None:
    with pytest.raises(TwentyApiTokenMissingError):
        TwentyCommentClient.from_env({TWENTY_API_TOKEN_ENV: "   "}, base_url=BASE_URL)


def test_zero_max_attempts_is_a_construction_error() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        TwentyCommentClient(BASE_URL, token=TOKEN, max_attempts=0)
