"""`pulse_core.client` — command submission with response classification (design decision 6).

Two conventions this module owns, so a writer never touches raw HTTP:

- **`PulseCoreClient.submit_command`** posts one generated `Command` (`pulse_core.generated`) to
  `POST /commands` and classifies the answer as `committed | replayed | rejected | transient` from
  the HTTP status and body — the client contract the command-api spec's response describes.
  `rejected` (auth failure or catalog violation) and `committed`/`replayed` return immediately;
  `transient` (a 5xx, a 429, or a network failure) retries with bounded exponential backoff, since
  a writer must not treat "the bus hiccuped" the same as "the catalog forbids this" or loop
  forever. The idempotency key is derived client-side (`pulse_core.idempotency`, D16) from this
  writer's own id plus the command's content, never left to the caller to construct by hand.
- **`subject_history`** reads one subject's committed events back from
  `GET /subjects/{subject_type}/{subject_key}/events` in ledger sequence, paging to exhaustion. It
  is the replay source a projection rebuilds from (pulse-demo-closeout design decision 5): the
  rebuild holds no ledger database credential, only the writer token it already declares with. A
  refused or unreadable answer raises — a rebuild that mistook a refusal for "this subject has no
  events" would repaint the subject's rows to nothing.
- **`consume(handler)`** wraps SQS receive → `handler` → delete, the same shape the converted
  ocean consumers use (`packages/ocean/services/agent-worker/src/consumer.py`): a message is
  deleted only once `handler` has returned without raising, so a failure is left to the queue's
  own visibility-timeout redelivery. `event_id` dedupe means a redelivered message — the ordinary
  cost of at-least-once delivery — is deleted without running `handler` a second time. This
  primitive now lives in `pulse_core.connector.consume` (task 2.3, connector-kit spec) and is
  re-exported here unchanged so this module's existing importers are unaffected.

The server side of this contract is wired (DNA-801): `pulse_ledger.api` accepts an
`idempotency_key` body field at the HTTP boundary, threads it to the idempotent commit path, and
echoes `replayed` in the commit response — so the `committed | replayed` classification above is
trustworthy end to end.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import httpx

from pulse_core.connector.consume import (
    ConsumeReport,
    ConsumerHandler,
    Deduper,
    InMemoryDeduper,
    Sleeper,
    consume,
    consume_once,
)
from pulse_core.generated import Command
from pulse_core.history import (
    DEFAULT_HISTORY_PAGE_SIZE,
    subject_history_path,
)
from pulse_core.idempotency import derive_idempotency_key

__all__ = [
    "COMMANDS_PATH",
    "CommandResponse",
    "ConsumeReport",
    "ConsumerHandler",
    "Deduper",
    "InMemoryDeduper",
    "PulseCoreClient",
    "Rejection",
    "ResponseClassification",
    "Sleeper",
    "SubjectHistoryRefusedError",
    "UnexpectedResponseError",
    "classify_response",
    "consume",
    "consume_once",
]

COMMANDS_PATH = "/commands"

#: A writer request answered with any of these carries a catalog or auth rejection: the command
#: never wrote anything, and retrying it unchanged will not either.
_REJECTED_STATUS = frozenset({401, 403, 422})

#: A writer request answered with any of these failed for a reason unrelated to the command's own
#: legality — the bus, the database, a load balancer's 429 — and is worth retrying unchanged.
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class SubjectHistoryRefusedError(RuntimeError):
    """A history read that did not come back as a readable history.

    One base for every way the read can fail to produce events — refused, transient past the retry
    budget, or answered with a body that is not a history — because every one of them has the same
    consequence for a caller: it does not know this subject's events and must not proceed as though
    the subject has none.

    Carries the status code and a reason naming the shape at fault. Never the response body, never
    the request's credential: a failed read is exactly when code reaches for the payload it was
    denied, and once C1 clears an event payload is patient data.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        self.reason = reason
        where = "no response" if status_code is None else f"HTTP {status_code}"
        super().__init__(f"subject history read failed ({where}): {reason}")


class HistoryRejectedError(SubjectHistoryRefusedError):
    """The ledger answered, and the answer was no — an auth refusal or an unknown subject type."""

    def __init__(self, status_code: int) -> None:
        super().__init__("the ledger refused the read", status_code=status_code)


class HistoryUnavailableError(SubjectHistoryRefusedError):
    """Still failing after the retry budget: a transport error or a transient status."""

    def __init__(self, attempts: int, *, status_code: int | None = None, cause: str | None = None) -> None:
        self.attempts = attempts
        detail = f"still unavailable after {attempts} attempts"
        super().__init__(detail if cause is None else f"{detail} ({cause})", status_code=status_code)


class MalformedHistoryError(SubjectHistoryRefusedError):
    """A 200 whose body is not a history. Names the shape at fault, never the content.

    One subclass per way the shape can be wrong, so a raise site passes a status code and nothing
    else — the message belongs to the exception, and no call site can quote a body into it.
    """

    shape = "the body is not the shape a history read returns"

    def __init__(self, *, status_code: int | None = None) -> None:
        super().__init__(f"the response is not a history: {self.shape}", status_code=status_code)


class HistoryBodyNotJsonError(MalformedHistoryError):
    shape = "the body is not JSON"


class HistoryBodyNotObjectError(MalformedHistoryError):
    shape = "the body is not a JSON object"


class HistoryEventsShapeError(MalformedHistoryError):
    shape = "'events' is not a list of objects"


class HistoryPageCursorError(SubjectHistoryRefusedError):
    """A full page whose last event carries no integer `seq`, so the next page has no cursor.

    Raised rather than paged again from the same cursor, which would loop forever, and rather than
    returned short, which would hand a rebuild a truncated history that folds cleanly to the wrong
    state.
    """

    def __init__(self) -> None:
        super().__init__("a full page's last event carries no integer 'seq'")


DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0


class ResponseClassification(str, Enum):
    """The four answers a submitted command can receive (design decision 6)."""

    COMMITTED = "committed"
    REPLAYED = "replayed"
    REJECTED = "rejected"
    TRANSIENT = "transient"


class UnexpectedResponseError(RuntimeError):
    """A status code this client has no classification rule for.

    Raised rather than guessed at: folding an unrecognised code into `rejected` or `transient`
    would silently misclassify whatever new status the service starts returning.
    """

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"unrecognised response status {status_code}: {body[:200]!r}")


@dataclass(frozen=True)
class Rejection:
    """Why a command was rejected, or why a transient attempt failed — never the request body."""

    message: str
    reason: str | None = None
    catalog_version: str | None = None


@dataclass(frozen=True)
class CommandResponse:
    """One classified answer to one submitted command."""

    classification: ResponseClassification
    status_code: int | None
    attempts: int = 1
    event_id: str | None = None
    recorded_at: str | None = None
    rule_version: str | None = None
    outbox_seq: int | None = None
    state: Mapping[str, object] | None = None
    rejection: Rejection | None = None

    @property
    def is_success(self) -> bool:
        """`True` for `committed` or `replayed` — the two answers that mean an event exists."""
        return self.classification in (ResponseClassification.COMMITTED, ResponseClassification.REPLAYED)


def _safe_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None


def _rejection_from_body(body: object, *, fallback_text: str) -> Rejection:
    detail = body.get("detail") if isinstance(body, Mapping) else None
    if isinstance(detail, Mapping):
        return Rejection(
            message=str(detail.get("message", detail)),
            reason=detail.get("reason") if isinstance(detail.get("reason"), str) else None,
            catalog_version=detail.get("catalog_version") if isinstance(detail.get("catalog_version"), str) else None,
        )
    if detail is not None:
        return Rejection(message=str(detail))
    return Rejection(message=fallback_text)


def classify_response(response: httpx.Response) -> CommandResponse:
    """Classify one HTTP response from `POST /commands` per design decision 6.

    Raises `UnexpectedResponseError` for a status this client has no rule for, rather than
    guessing — the four classifications are exhaustive only for the statuses `pulse_ledger.api`
    is documented to return.
    """
    status = response.status_code
    if status in _REJECTED_STATUS:
        body = _safe_json(response)
        return CommandResponse(
            classification=ResponseClassification.REJECTED,
            status_code=status,
            rejection=_rejection_from_body(body, fallback_text=response.text),
        )
    if status in _TRANSIENT_STATUS:
        return CommandResponse(
            classification=ResponseClassification.TRANSIENT,
            status_code=status,
            rejection=Rejection(message=response.text or f"HTTP {status}"),
        )
    if 200 <= status < 300:
        body = _safe_json(response)
        mapping = body if isinstance(body, Mapping) else {}
        replayed = bool(mapping.get("replayed", False))
        return CommandResponse(
            classification=ResponseClassification.REPLAYED if replayed else ResponseClassification.COMMITTED,
            status_code=status,
            event_id=mapping.get("event_id"),
            recorded_at=mapping.get("recorded_at"),
            rule_version=mapping.get("rule_version"),
            outbox_seq=mapping.get("outbox_seq"),
            state=mapping.get("state"),
        )
    raise UnexpectedResponseError(status, response.text)


#: `command.model_dump()` fields that are structural (already placed elsewhere in the wire body)
#: rather than part of the free-form `payload` the ledger stores alongside them.
_STRUCTURAL_COMMAND_FIELDS = frozenset({"command_type", "subject_type", "subject_key", "to_state"})


def _command_body(
    command: Command,
    *,
    effective_at: datetime,
    evidence: Mapping[str, object] | None,
    evidence_class: str | None,
    epoch: str | None,
    correlation_id: uuid.UUID | None,
    causation_id: uuid.UUID | None,
) -> dict[str, object]:
    """The generated `Command` as the JSON body `POST /commands` expects.

    A command's structural fields (`subject_type`, `subject_key`, `to_state`) map onto the
    declaration's own fields of the same name; `command_type` becomes `event_type`; everything
    else the command carries (`outcome`, `reason`, `rule_version`, `as_of`, `lineage`, `system`,
    `value`, ...) is free-form as far as the wire is concerned and travels in `payload`, exactly as
    `pulse_ledger.commit.Declaration.event_payload` expects it. Attribution fields
    (`actor_type`/`actor_id`/`actor_authority`/`producer`) are never part of this body — the
    credential supplies them server-side, and a body that carried them would be rejected as a
    spoof attempt.
    """
    fields = command.model_dump(mode="json")
    to_state = fields.pop("to_state", None)
    payload = {key: value for key, value in fields.items() if key not in _STRUCTURAL_COMMAND_FIELDS}
    body: dict[str, object] = {
        "subject_type": command.subject_type,
        "subject_key": command.subject_key,
        "event_type": command.command_type,
        "effective_at": effective_at.isoformat(),
        "payload": payload,
    }
    if to_state is not None:
        body["to_state"] = to_state
    if evidence is not None:
        body["evidence"] = dict(evidence)
    if evidence_class is not None:
        body["evidence_class"] = evidence_class
    if epoch is not None:
        body["epoch"] = epoch
    if correlation_id is not None:
        body["correlation_id"] = str(correlation_id)
    if causation_id is not None:
        body["causation_id"] = str(causation_id)
    return body


def _default_sleep(seconds: float) -> None:

    time.sleep(seconds)


def _backoff_delay(attempt: int, *, base: float, maximum: float) -> float:
    """Exponential backoff, capped: attempt 1 waits `base`, attempt 2 waits `2*base`, ..."""
    delay = base * (2 ** (attempt - 1))
    return delay if delay < maximum else maximum


class PulseCoreClient:
    """A writer's connection to one `pulse_ledger` command API.

    `transport` is the seam tests use (`httpx.MockTransport`) to fake the API boundary without a
    live network, per this change's testing posture — production wiring passes none and gets a
    real `httpx.Client` against `base_url`.
    """

    def __init__(
        self,
        base_url: str,
        *,
        writer_id: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
        sleep: Sleeper = _default_sleep,
    ) -> None:
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        self._writer_id = writer_id
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

    def __enter__(self) -> PulseCoreClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def submit_command(
        self,
        command: Command,
        *,
        effective_at: datetime,
        evidence: Mapping[str, object] | None = None,
        evidence_class: str | None = None,
        epoch: str | None = None,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
    ) -> CommandResponse:
        """Submit one command, retrying only a `transient` classification.

        `effective_at` must be timezone-aware — it doubles as the idempotency key's
        `logical_time` (D16), and a naive instant has no determined meaning there either.
        """
        body = _command_body(
            command,
            effective_at=effective_at,
            evidence=evidence,
            evidence_class=evidence_class,
            epoch=epoch,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        body["idempotency_key"] = derive_idempotency_key(
            writer_id=self._writer_id,
            subject_type=command.subject_type,
            subject_key=command.subject_key,
            command_type=command.command_type,
            payload=body["payload"],  # type: ignore[arg-type]
            logical_time=effective_at,
        )
        return self._post_with_retry(body)

    def _post_with_retry(self, body: Mapping[str, object]) -> CommandResponse:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.post(COMMANDS_PATH, json=body)
                result = classify_response(response)
            except httpx.TransportError as exc:
                result = CommandResponse(
                    classification=ResponseClassification.TRANSIENT,
                    status_code=None,
                    rejection=Rejection(message=str(exc)),
                )
            if result.classification is not ResponseClassification.TRANSIENT or attempt >= self._max_attempts:
                return dataclasses.replace(result, attempts=attempt)
            self._sleep(_backoff_delay(attempt, base=self._base_delay, maximum=self._max_delay))

    def subject_history(
        self,
        subject_type: str,
        subject_key: str,
        *,
        page_size: int = DEFAULT_HISTORY_PAGE_SIZE,
    ) -> list[dict[str, object]]:
        """Every committed event for one subject, in ledger sequence, paged to exhaustion.

        Ledger sequence is the per-subject `seq` the relay publishes in, so the list this returns
        is the order a live consumer saw these events in — which is what makes a rebuild from it
        agree with incremental apply rather than merely resemble it.

        Paging is a keyset walk on `seq`: each request asks for events after the last one received,
        so a subject still being written to can neither skip nor repeat an event across a page
        boundary. A page shorter than `page_size` ends the walk.

        Raises `SubjectHistoryRefusedError` for anything that is not a readable history — a
        refusal, a transient failure past the retry budget, or a malformed body. Never an empty
        list: "no events" and "I could not read the events" are different answers, and a rebuild
        that confuses them repaints a subject's rows to nothing.
        """
        events: list[dict[str, object]] = []
        after_seq: int | None = None
        while True:
            params: dict[str, int] = {"limit": page_size}
            if after_seq is not None:
                params["after_seq"] = after_seq
            page = self._get_history_page(subject_history_path(subject_type, subject_key), params)
            events.extend(page)
            if len(page) < page_size:
                return events
            last_seq = page[-1].get("seq")
            if not isinstance(last_seq, int):
                raise HistoryPageCursorError()
            after_seq = last_seq

    def _get_history_page(self, path: str, params: Mapping[str, int]) -> list[dict[str, object]]:
        """One page, retrying only a transient answer — the same policy `submit_command` applies."""
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.get(path, params=dict(params))
            except httpx.TransportError as exc:
                if attempt >= self._max_attempts:
                    raise HistoryUnavailableError(attempt, cause=type(exc).__name__) from exc
                self._sleep(_backoff_delay(attempt, base=self._base_delay, maximum=self._max_delay))
                continue
            if response.status_code in _TRANSIENT_STATUS:
                if attempt >= self._max_attempts:
                    raise HistoryUnavailableError(attempt, status_code=response.status_code)
                self._sleep(_backoff_delay(attempt, base=self._base_delay, maximum=self._max_delay))
                continue
            if response.status_code != 200:
                raise HistoryRejectedError(response.status_code)
            return _history_events(response)


def _history_events(response: httpx.Response) -> list[dict[str, object]]:
    """The `events` list out of a history response, or a refusal naming the shape at fault.

    Every check here names a shape and never a value: the body is a list of event envelopes, and an
    envelope's payload is the one thing in this module that will carry PHI once C1 clears.
    """
    status = response.status_code
    try:
        body: object = response.json()
    except ValueError as exc:
        raise HistoryBodyNotJsonError(status_code=status) from exc
    if not isinstance(body, Mapping):
        raise HistoryBodyNotObjectError(status_code=status)
    events = body.get("events")
    if not isinstance(events, list) or not all(isinstance(event, Mapping) for event in events):
        raise HistoryEventsShapeError(status_code=status)
    return [dict(event) for event in events]
