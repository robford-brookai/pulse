"""The outbound Twenty rejection-commentary adapter (twenty-kanban-webhook-ingress task 2.2,
design decision 6; note+noteTarget rework per twenty-dev-instance 6.7).

Everything runs at the HTTP boundary against `httpx.MockTransport` — no socket is ever opened, and
an autouse fixture enforces that rather than trusting a command-line flag. The PHI scans use the
recognizable fake demographics from the 1.1 fixtures (`Canary`, case last names): a note body or
error message is clean only if none of them appear.

7.2's live run falsified the original `POST /rest/comments` pin — v2.30 has no `comment` object.
The record-attached commentary surface is a `note` (`POST /rest/notes`) plus a `noteTarget`
(`POST /rest/noteTargets`) binding it to the record by the flat relation column
(`patientProgramId`), so every posting test here asserts both calls and their flat keys.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import pytest_socket
from pulse_ledger.twenty.client import (
    NOTE_TARGETS_PATH,
    NOTES_PATH,
    TWENTY_API_TOKEN_ENV,
    CommentPostError,
    MalformedCardRefError,
    RejectionReceipt,
    TwentyApiTokenMissingError,
    TwentyCommentClient,
    format_rejection_comment,
)
from twenty_fixtures import load_fixture_json

BASE_URL = "https://twenty.example.test"
#: Long enough to be a plausible credential; recognizable so a leak scan can grep for it.
TOKEN = "twenty-api-token-canary-0123456789abcdef"  # noqa: S105 — synthetic test credential

RECORD_ID = "twenty-record-patientprogram-0002"
CARD_REF = f"patientProgram:{RECORD_ID}"
NOTE_ID = "twenty-note-0001"

RECEIPT = RejectionReceipt(
    card_ref=CARD_REF,
    from_state="activated",
    to_state="registered",
    reason="transition_not_permitted",
    catalog_version="1.0.0",
)


def _note_created(note_id: str = NOTE_ID) -> httpx.Response:
    """The live singular-create answer shape: `data.createNote`, per the verified convention."""
    return httpx.Response(201, json={"data": {"createNote": {"id": note_id}}})


def _target_created() -> httpx.Response:
    return httpx.Response(201, json={"data": {"createNoteTarget": {"id": "twenty-notetarget-0001"}}})


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


# --- posting: a note then its target binding, flat keys, bearer credential on both ---


def test_posting_creates_a_note_then_a_note_target_with_flat_keys() -> None:
    requests: list[httpx.Request] = []
    client = _recording_client([_note_created(), _target_created()], requests)
    body = format_rejection_comment(RECEIPT)

    client.create_comment(CARD_REF, RECEIPT.reason, body)

    assert len(requests) == 2

    note_request = requests[0]
    assert note_request.method == "POST"
    assert note_request.url.path == NOTES_PATH
    assert note_request.headers["Authorization"] == f"Bearer {TOKEN}"
    note_wire = json.loads(note_request.content)
    assert note_wire == {"title": RECEIPT.reason, "body": body}

    target_request = requests[1]
    assert target_request.method == "POST"
    assert target_request.url.path == NOTE_TARGETS_PATH
    assert target_request.headers["Authorization"] == f"Bearer {TOKEN}"
    target_wire = json.loads(target_request.content)
    assert target_wire == {"noteId": NOTE_ID, "patientProgramId": RECORD_ID}


def test_the_note_body_is_the_receipt_text_and_carries_no_payload_field() -> None:
    requests: list[httpx.Request] = []
    client = _recording_client([_note_created(), _target_created()], requests)
    body = format_rejection_comment(RECEIPT)

    client.create_comment(CARD_REF, RECEIPT.reason, body)

    note_wire = json.loads(requests[0].content)
    assert "activated" in note_wire["body"]
    assert "registered" in note_wire["body"]
    assert "transition_not_permitted" in note_wire["body"]
    for leaked in _demographic_strings():
        assert leaked not in note_wire["body"]
        assert leaked not in note_wire["title"]


def test_the_relation_column_is_derived_from_the_card_refs_object_name() -> None:
    """The flat relation-column convention: `<objectName>Id`, never a nested relation object."""
    requests: list[httpx.Request] = []
    client = _recording_client([_note_created(), _target_created()], requests)

    client.create_comment("otherBoard:record-0009", "some_reason", "some receipt text")

    target_wire = json.loads(requests[1].content)
    assert target_wire == {"noteId": NOTE_ID, "otherBoardId": "record-0009"}


def test_a_card_ref_without_an_object_and_record_id_is_refused_before_any_call() -> None:
    requests: list[httpx.Request] = []
    client = _recording_client([_note_created()], requests)

    with pytest.raises(MalformedCardRefError, match="not-a-record-ref"):
        client.create_comment("not-a-record-ref", RECEIPT.reason, "body")

    assert requests == []


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
        client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert len(requests) == 3
    assert sleeps == [0.5, 1.0]  # exponential from the base delay, one sleep between attempts
    error = excinfo.value
    assert error.card_ref == CARD_REF
    assert error.attempts == 3
    assert error.status_code == 503
    assert CARD_REF in str(error)
    for leaked in (TOKEN, "upstream unavailable", *_demographic_strings()):
        assert leaked not in str(error)
        assert leaked not in repr(error)


def test_timeout_retries_then_succeeds() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    client = _recording_client(
        [
            httpx.ConnectTimeout("connection timed out"),
            httpx.ReadTimeout("read timed out"),
            _note_created(),
            _target_created(),
        ],
        requests,
        sleep=sleeps.append,
    )

    client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert len(requests) == 4
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
        client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert len(requests) == 2
    assert excinfo.value.status_code is None
    assert CARD_REF in str(excinfo.value)


def test_4xx_is_permanent_with_no_retry() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    client = _recording_client([httpx.Response(404, text="no such object")], requests, sleep=sleeps.append)

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert len(requests) == 1
    assert sleeps == []
    assert excinfo.value.status_code == 404
    assert excinfo.value.attempts == 1
    assert "no such object" not in str(excinfo.value)


def test_a_target_failure_after_a_created_note_is_typed_and_echoes_no_body() -> None:
    """The second leg failing must surface like the first: card ref, attempts, status — no bodies."""
    requests: list[httpx.Request] = []
    client = _recording_client(
        [_note_created(), httpx.Response(400, text="relation refused")],
        requests,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert len(requests) == 2  # the note posted, the target was refused, nothing retried a 400
    assert excinfo.value.status_code == 400
    assert CARD_REF in str(excinfo.value)
    for leaked in ("relation refused", NOTE_ID, TOKEN, *_demographic_strings()):
        assert leaked not in str(excinfo.value)


def test_a_note_create_answer_without_an_id_fails_without_a_target_call() -> None:
    """A 2xx that carries no note id cannot be bound — permanent, and no response echo."""
    requests: list[httpx.Request] = []
    client = _recording_client(
        [httpx.Response(201, json={"data": {"createNote": {"title": "should never be echoed"}}})],
        requests,
    )

    with pytest.raises(CommentPostError) as excinfo:
        client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert len(requests) == 1
    assert CARD_REF in str(excinfo.value)
    assert "should never be echoed" not in str(excinfo.value)


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
        client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))

    assert TOKEN not in caplog.text
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)
    for record in caplog.records:
        assert TOKEN not in record.getMessage()


# --- configuration: the token comes from the environment and its absence fails loud ---


def test_from_env_builds_a_client_with_the_configured_token() -> None:
    requests: list[httpx.Request] = []
    responses = [_note_created(), _target_created()]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses[len(requests) - 1]

    client = TwentyCommentClient.from_env(
        {TWENTY_API_TOKEN_ENV: TOKEN},
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    client.create_comment(CARD_REF, RECEIPT.reason, format_rejection_comment(RECEIPT))
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert requests[1].headers["Authorization"] == f"Bearer {TOKEN}"


def test_from_env_refuses_a_missing_token() -> None:
    with pytest.raises(TwentyApiTokenMissingError):
        TwentyCommentClient.from_env({}, base_url=BASE_URL)


def test_from_env_refuses_a_blank_token() -> None:
    with pytest.raises(TwentyApiTokenMissingError):
        TwentyCommentClient.from_env({TWENTY_API_TOKEN_ENV: "   "}, base_url=BASE_URL)


def test_zero_max_attempts_is_a_construction_error() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        TwentyCommentClient(BASE_URL, token=TOKEN, max_attempts=0)
