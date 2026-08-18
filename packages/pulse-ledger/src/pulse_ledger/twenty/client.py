"""The thin outbound rejection-commentary adapter (twenty-kanban-webhook-ingress design decision 6).

The one new external surface in this change, deliberately narrow: rejection-commentary creates
against Twenty's REST API and nothing else — no reads, no other verbs, no general Twenty client.
Phase 3 decides whether to extend or extract it. The bearer credential comes from
`PULSE_LEDGER_TWENTY_API_TOKEN` and, like every credential in `pulse_ledger.auth`, lives in the
environment and nowhere else: no error or log line here ever carries the token, a response body,
or the note body.

`format_rejection_comment` builds the note body exclusively from the rejection receipt — the
violated states, the catalog's coded reason, the catalog version, and the fixed "state of record
is unchanged" — never from webhook payload fields, which are presumed PHI. The receipt itself is
built by the route (task 3.2) from `IllegalTransitionError` fields plus the mapping's card ref.

The original pin here was `POST /rest/comments`. 7.2's live run (assertion 9) falsified it — v2.30
has no `comment` object; the record-attached commentary surface is a **note** plus a **noteTarget**
binding it to the record (task 6.7). So one rejection is two creates: `POST /rest/notes` with the
reason code as title and the receipt text as body, then `POST /rest/noteTargets` with the note id
and the flat relation column (`<objectName>Id`, the live-verified relation-column convention).
The two create-response shapes themselves are pinned, not yet individually exercised live, per
`docs/contracts/consumes.md`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from pulse_ledger.auth import CredentialConfigurationError

TWENTY_API_TOKEN_ENV = "PULSE_LEDGER_TWENTY_API_TOKEN"  # noqa: S105 — a variable name, not a secret

#: The live commentary surface (task 6.7): a `note` record, bound to its card by a `noteTarget`.
NOTES_PATH = "/rest/notes"
NOTE_TARGETS_PATH = "/rest/noteTargets"

#: Pinned from the live-verified singular-create convention (`create` + capitalized singular, the
#: shape the seed loader verified for batch creates 2026-08-17): where a note create answers with
#: the created record. A drift here surfaces as `CommentPostError`, never as a silent misread.
NOTE_CREATED_KEY = "createNote"

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0


class TwentyApiTokenMissingError(CredentialConfigurationError):
    """The commentary adapter was asked for but its credential is unset or blank. Raised at boot."""

    def __init__(self) -> None:
        super().__init__(f"{TWENTY_API_TOKEN_ENV} is not set (or is blank); the comment adapter cannot authenticate")


class MalformedCardRefError(ValueError):
    """The card ref is not the `object:recordId` shape `RecordRef` formats — a wiring bug.

    Raised before any HTTP call: without the object name there is no relation column to bind the
    note with. Names the card ref only, which is an identifier by construction.
    """

    def __init__(self, card_ref: str) -> None:
        super().__init__(f"card ref {card_ref!r} is not of the form 'object:recordId'")


class CommentPostError(Exception):
    """Rejection commentary failed for good — retries exhausted, or a non-retryable answer.

    Names the card ref, the attempt count, and the final HTTP status (`None` for a transport
    failure) — never the credential, the note title or body, or anything from a response body,
    because a commentary failure is exactly when something gets logged. `detail` overrides the
    derived status text for failures that are not an HTTP status (a create answer with no id).
    """

    def __init__(self, card_ref: str, *, attempts: int, status_code: int | None, detail: str | None = None) -> None:
        self.card_ref = card_ref
        self.attempts = attempts
        self.status_code = status_code
        if detail is None:
            detail = f"HTTP {status_code}" if status_code is not None else "transport error"
        super().__init__(f"rejection commentary on card {card_ref!r} failed after {attempts} attempt(s): {detail}")


@dataclass(frozen=True)
class RejectionReceipt:
    """What an illegal drag produces (twenty-rejection-feedback spec) — states, coded reason,
    catalog version, card ref, and nothing from the payload.

    The route (task 3.2) builds it exclusively from `IllegalTransitionError` fields plus the
    mapping's card ref. `from_state` is `None` when the rejected declaration was a subject's
    first, mirroring `IllegalTransitionError`.
    """

    card_ref: str
    from_state: str | None
    to_state: str
    reason: str
    catalog_version: str


def format_rejection_comment(receipt: RejectionReceipt) -> str:
    """The note body for one rejection — receipt fields only, never payload content.

    Tells the user who dragged the card the attempted transition, the catalog's coded reason,
    the catalog version consulted, and that the state of record is unchanged. Everything in the
    returned string comes from the receipt's own fields; there is deliberately no parameter
    through which payload content could reach it.
    """
    origin = repr(receipt.from_state) if receipt.from_state is not None else "no prior state"
    return (
        f"This move was not applied: {origin} -> {receipt.to_state!r} is not a permitted "
        f"transition — {receipt.reason} (catalog {receipt.catalog_version}). "
        f"The state of record is unchanged."
    )


Sleeper = Callable[[float], None]


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def _backoff_delay(attempt: int, *, base: float, maximum: float) -> float:
    """Exponential backoff, capped: attempt 1 waits `base`, attempt 2 waits `2*base`, ..."""
    delay = base * (2 ** (attempt - 1))
    return delay if delay < maximum else maximum


class TwentyCommentClient:
    """Rejection-commentary creates against one Twenty instance, and no other verb.

    `transport` is the seam tests use (`httpx.MockTransport`) to fake the HTTP boundary without a
    live network — the same convention as `pulse_core.client.PulseCoreClient`. A 5xx or a
    transport failure (timeouts included) retries with bounded exponential backoff; any other
    non-2xx is permanent immediately — a 404 or 401 does not get better by asking again. Each of
    the two creates gets its own attempt budget.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        sleep: Sleeper = _default_sleep,
    ) -> None:
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        self._max_attempts = max_attempts
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
        *,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        sleep: Sleeper = _default_sleep,
    ) -> TwentyCommentClient:
        """Build the adapter with the credential from `PULSE_LEDGER_TWENTY_API_TOKEN`.

        A missing or blank token raises `TwentyApiTokenMissingError` — a
        `CredentialConfigurationError`, so wiring the adapter into an enabled route without its
        credential is a boot failure, same posture as the webhook secret.
        """
        token = environ.get(TWENTY_API_TOKEN_ENV)
        if token is None or not token.strip():
            raise TwentyApiTokenMissingError()
        return cls(
            base_url,
            token=token,
            transport=transport,
            timeout=timeout,
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            sleep=sleep,
        )

    def __enter__(self) -> TwentyCommentClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def create_comment(self, card_ref: str, title: str, body: str) -> None:
        """Attach one rejection note to one card, or raise `CommentPostError`.

        Two creates: the note (`title` is the catalog's coded reason, `body` the receipt text),
        then the noteTarget binding it to the record — `noteId` plus the flat relation column
        derived from the card ref's object name (`patientProgramId` for the v1 board). Retries
        only what retrying can fix — 5xx and transport failures — up to `max_attempts` per call,
        sleeping the capped exponential backoff between attempts. The raised error names the card
        ref only; the caller (task 3.2) logs it the same way and still returns the receipt, so a
        broken commentary channel degrades feedback, never rejection correctness.
        """
        object_name, _, record_id = card_ref.partition(":")
        if not object_name or not record_id:
            raise MalformedCardRefError(card_ref)

        # Live v2.30 pin (demo3 assertion 9, 2026-08-18): `note` has no `body` field — the
        # rich-text column is `bodyV2`, created as `{"markdown": ...}` (server converts to
        # blocknote on write; a flat string is rejected).
        note_response = self._post_with_retry(NOTES_PATH, {"title": title, "bodyV2": {"markdown": body}}, card_ref)
        note_id = _created_note_id(note_response)
        if note_id is None:
            raise CommentPostError(
                card_ref,
                attempts=1,
                status_code=note_response.status_code,
                detail="the note create answered success but carried no note id",
            )
        self._post_with_retry(NOTE_TARGETS_PATH, {"noteId": note_id, f"{object_name}Id": record_id}, card_ref)

    def _post_with_retry(self, path: str, payload: Mapping[str, object], card_ref: str) -> httpx.Response:
        """One create with the shared retry posture; returns the successful response."""
        attempt = 0
        while True:
            attempt += 1
            status_code: int | None
            try:
                response = self._http.post(path, json=dict(payload))
            except httpx.TransportError:
                status_code = None
            else:
                if response.is_success:
                    return response
                status_code = response.status_code
                if response.status_code < 500:
                    raise CommentPostError(card_ref, attempts=attempt, status_code=status_code)
            if attempt >= self._max_attempts:
                raise CommentPostError(card_ref, attempts=attempt, status_code=status_code)
            self._sleep(_backoff_delay(attempt, base=self._base_delay, maximum=self._max_delay))


def _created_note_id(response: httpx.Response) -> str | None:
    """The created note's id, or `None` — the response body is dropped where it is read."""
    try:
        parsed = response.json()
    except ValueError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    data = parsed.get("data")
    if not isinstance(data, Mapping):
        return None
    record = data.get(NOTE_CREATED_KEY)
    if not isinstance(record, Mapping):
        return None
    note_id = record.get("id")
    return str(note_id) if note_id is not None else None
