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
- **`consume(handler)`** wraps SQS receive → `handler` → delete, the same shape the converted
  ocean consumers use (`packages/ocean/services/agent-worker/src/consumer.py`): a message is
  deleted only once `handler` has returned without raising, so a failure is left to the queue's
  own visibility-timeout redelivery. `event_id` dedupe means a redelivered message — the ordinary
  cost of at-least-once delivery — is deleted without running `handler` a second time.

The server side of this contract is wired (DNA-801): `pulse_ledger.api` accepts an
`idempotency_key` body field at the HTTP boundary, threads it to the idempotent commit path, and
echoes `replayed` in the commit response — so the `committed | replayed` classification above is
trustworthy end to end.
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

import httpx

from pulse_core.generated import Command
from pulse_core.idempotency import derive_idempotency_key

COMMANDS_PATH = "/commands"

#: A writer request answered with any of these carries a catalog or auth rejection: the command
#: never wrote anything, and retrying it unchanged will not either.
_REJECTED_STATUS = frozenset({401, 403, 422})

#: A writer request answered with any of these failed for a reason unrelated to the command's own
#: legality — the bus, the database, a load balancer's 429 — and is worth retrying unchanged.
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})

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


Sleeper = Callable[[float], None]


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


# --- consume(handler): SQS receive / process / delete, event_id dedupe (design decision 6) ---

ConsumerHandler = Callable[[Mapping[str, object]], None]


class Deduper(Protocol):
    """Tracks which `event_id`s this consumer has already run `handler` for."""

    def seen(self, event_id: str) -> bool: ...

    def mark(self, event_id: str) -> None: ...


class InMemoryDeduper:
    """The default `Deduper`: good for one process's lifetime, gone on restart.

    A restart re-runs `handler` for whatever was in flight, which is exactly the at-least-once
    contract `handler` must already tolerate — this dedupe is an optimization against ordinary
    redelivery within one run, not a durability guarantee across runs.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, event_id: str) -> bool:
        return event_id in self._seen

    def mark(self, event_id: str) -> None:
        self._seen.add(event_id)


@dataclass(frozen=True)
class ConsumeReport:
    """What one `consume_once` pass did, for logging and tests."""

    processed: int = 0
    deduped: int = 0
    failed: int = 0


def _envelope_from_body(body: object) -> dict[str, object] | None:
    """Extract the event envelope from a parsed SQS message body.

    An EventBridge rule delivers the envelope whole inside `detail`; a body with no `detail` key
    is accepted as a bare envelope so local tooling can send straight to the queue — the same
    convention `agent-worker`'s consumer uses.
    """
    if not isinstance(body, dict):
        return None
    detail = body.get("detail", body)
    return detail if isinstance(detail, dict) else None


def consume_once(
    handler: ConsumerHandler,
    *,
    sqs_client: Any,
    queue_url: str,
    deduper: Deduper,
    max_messages: int = 10,
    wait_time_seconds: int = 20,
) -> ConsumeReport:
    """One receive/process/delete pass against one SQS queue.

    A message is deleted only after `handler` returns without raising: a failure is left for the
    queue's own visibility-timeout redelivery and its DLQ redrive policy, never swallowed here. A
    message whose envelope's `event_id` this deduper has already seen is deleted *without* calling
    `handler` again — the point of the dedupe — and a malformed message (unparseable body, no
    envelope) is dropped rather than retried forever.
    """
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=wait_time_seconds,
    )
    report = ConsumeReport()
    for message in response.get("Messages", []):
        receipt_handle = message.get("ReceiptHandle", "")
        try:
            body = json.loads(message["Body"])
        except (json.JSONDecodeError, KeyError):
            report = dataclasses.replace(report, failed=report.failed + 1)
            continue
        envelope = _envelope_from_body(body)
        if envelope is None:
            report = dataclasses.replace(report, failed=report.failed + 1)
            continue

        event_id = envelope.get("event_id")
        event_id_str = str(event_id) if event_id is not None else None
        if event_id_str is not None and deduper.seen(event_id_str):
            sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            report = dataclasses.replace(report, deduped=report.deduped + 1)
            continue

        try:
            handler(envelope)
        except Exception:
            report = dataclasses.replace(report, failed=report.failed + 1)
            continue

        if event_id_str is not None:
            deduper.mark(event_id_str)
        sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        report = dataclasses.replace(report, processed=report.processed + 1)
    return report


def consume(
    handler: ConsumerHandler,
    *,
    queue_url: str,
    sqs_client: Any = None,
    deduper: Deduper | None = None,
    max_messages: int = 10,
    wait_time_seconds: int = 20,
    error_backoff_seconds: float = 5.0,
    sleep: Sleeper = _default_sleep,
    iterations: int | None = None,
) -> None:
    """Run `consume_once` in a loop — forever, or `iterations` times for a bounded test run.

    `sqs_client` defaults to a real `boto3` client, imported lazily so importing this module never
    requires `boto3` to be installed; a test always supplies a fake one instead. A pass that raises
    (a transport error `receive_message`/`delete_message` didn't swallow itself) is logged nowhere
    here — the caller's own logging wraps `handler` — and backed off before the next attempt so a
    persistent outage does not spin the loop.
    """
    if sqs_client is None:
        import boto3

        sqs_client = boto3.client("sqs")
    active_deduper = deduper or InMemoryDeduper()

    count = 0
    while iterations is None or count < iterations:
        try:
            consume_once(
                handler,
                sqs_client=sqs_client,
                queue_url=queue_url,
                deduper=active_deduper,
                max_messages=max_messages,
                wait_time_seconds=wait_time_seconds,
            )
        except Exception:
            sleep(error_backoff_seconds)
        count += 1
