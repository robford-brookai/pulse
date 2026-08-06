"""`identity.service` — the consumption entrypoint, the composition root (task 4.3).

`build_handler(...)` wires the 3.2 live lookup adapter into the 3.1 matcher and the 4.1/4.2
resolver behind `pulse_core.client`'s `ConsumerHandler` shape — this module owns none of the
matching, resolving, or quarantining logic itself; it only parses one `referral.received`
envelope, calls `identity.matcher.resolve`, and routes the decision to `identity.resolver.act`
(Match/Mint) or `identity.resolver.quarantine` (Ambiguous). `consume_referrals(...)` then hands
that handler to `pulse_core.client.consume(handler, queue_url=...)` for the receive/process/delete
loop: one referral per invocation, `event_id` dedupe, delete only after the handler returns
without raising — so a crash between committing this referral's commands and the queue delete
is left to ordinary SQS redelivery, and redelivery converges rather than duplicates because every
command and the quarantine hold fact already carry a D16 idempotency key (resolver.py, design
decision 5/6).

**The `referral.received` envelope this module parses** (a local contract — nothing upstream
registers it yet; register it in `docs/contracts/publishes.md` alongside the matcher entrypoint
per task 5.2 once ratified):

```json
{
  "event_id": "018f3c2a-7b6e-7c4d-9a1b-2f3e4d5c6b7a",
  "referral_key": "referral-0001",
  "effective_at": "2026-08-01T12:00:00Z",
  "payload": {
    "demographics": {"first_name": "...", "last_name": "...", "dob": "...", "sex": "..."},
    "identifiers": [{"system": "MRN-ACME", "value": "..."}]
  }
}
```

`effective_at` (or its `occurred_at` alias, per `pulse_ledger.commit`'s convention) must be an
aware ISO 8601 instant — it becomes both the resolver's D16 logical time and the referral's
business time, never wall-clock "now" (resolver.py's `act`/`quarantine` docstrings). `identifiers`
defaults to none.

**Design decision 3's flagged path (a):** a naive `logger.exception(..., envelope)` on a handler
failure would serialize the envelope, which carries referral demographics in `payload.demographics`
— this module never logs the envelope, or any value out of it, on any failure path. Every log
line here names `event_id` and, once parsed, the referral's own key — never a demographic value,
never an identifier value. `parse_referral_envelope`'s own errors name the missing/malformed
*field*, never a value (the same convention `normalize.py`'s `NormalizationError` and
`matcher.py`'s rejection errors already follow).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

import psycopg
from pulse_core.client import ConsumerHandler, Deduper, PulseCoreClient, Sleeper, consume

from identity.lookup import LedgerLookup
from identity.matcher import Ambiguous, CandidateLookup, ExternalIdentifier, Referral, resolve
from identity.normalize import Demographics
from identity.resolver import PersonKeyFactory, default_person_key
from identity.resolver import act as resolver_act
from identity.resolver import quarantine as resolver_quarantine

logger = logging.getLogger("identity.service")

__all__ = [
    "ParsedReferral",
    "ReferralEnvelopeError",
    "build_handler",
    "consume_referrals",
    "main",
    "parse_referral_envelope",
]


class ReferralEnvelopeError(ValueError):
    """A `referral.received` envelope is missing or malformed. Names the field only — the
    fixture-demographic caplog scan (task 4.3) depends on this never echoing a value."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"referral.received envelope missing or malformed field {field!r}")


@dataclass(frozen=True)
class ParsedReferral:
    """One envelope's referral, decoded into the shapes `matcher.resolve`/`resolver.act` take."""

    referral_key: str
    triggering_event_id: str
    effective_at: datetime
    referral: Referral


def _require(envelope: Mapping[str, object], field: str) -> object:
    value = envelope.get(field)
    if value is None:
        raise ReferralEnvelopeError(field)
    return value


def _parse_effective_at(envelope: Mapping[str, object]) -> datetime:
    raw = envelope.get("effective_at", envelope.get("occurred_at"))
    if raw is None:
        raise ReferralEnvelopeError("effective_at")
    if isinstance(raw, datetime):
        value = raw
    else:
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            raise ReferralEnvelopeError("effective_at") from None
    if value.tzinfo is None:
        # A naive instant has no determined D16 meaning (resolver.py: "effective_at must be
        # timezone-aware"); reject here rather than let PulseCoreClient fail deep inside act().
        raise ReferralEnvelopeError("effective_at")
    return value


def _parse_demographics(payload: Mapping[str, object]) -> Demographics:
    raw = payload.get("demographics")
    if not isinstance(raw, Mapping):
        raise ReferralEnvelopeError("payload.demographics")
    demographics_raw = cast("Mapping[str, object]", raw)
    try:
        dob = demographics_raw["dob"]
        last_name = demographics_raw["last_name"]
        first_name = demographics_raw["first_name"]
        sex = demographics_raw["sex"]
    except KeyError as exc:
        raise ReferralEnvelopeError(f"payload.demographics.{exc.args[0]}") from None
    return Demographics(
        last_name=str(last_name),
        first_name=str(first_name),
        dob=dob if isinstance(dob, date) else str(dob),
        sex=str(sex),
    )


def _parse_identifiers(payload: Mapping[str, object]) -> tuple[ExternalIdentifier, ...]:
    raw = payload.get("identifiers", [])
    if not isinstance(raw, list | tuple):
        raise ReferralEnvelopeError("payload.identifiers")
    entries_raw = cast("Sequence[object]", raw)
    identifiers: list[ExternalIdentifier] = []
    for entry in entries_raw:
        if not isinstance(entry, Mapping):
            raise ReferralEnvelopeError("payload.identifiers[]")
        entry_raw = cast("Mapping[str, object]", entry)
        try:
            identifiers.append(ExternalIdentifier(system=str(entry_raw["system"]), value=str(entry_raw["value"])))
        except KeyError as exc:
            raise ReferralEnvelopeError(f"payload.identifiers[].{exc.args[0]}") from None
    return tuple(identifiers)


def parse_referral_envelope(envelope: Mapping[str, object]) -> ParsedReferral:
    """Decode one `referral.received` envelope. Raises `ReferralEnvelopeError` naming the first
    missing/malformed field it finds — never a value, per this module's own logging contract."""
    event_id = _require(envelope, "event_id")
    referral_key = _require(envelope, "referral_key")
    effective_at = _parse_effective_at(envelope)
    raw_payload = envelope.get("payload", {})
    if not isinstance(raw_payload, Mapping):
        raise ReferralEnvelopeError("payload")
    payload = cast("Mapping[str, object]", raw_payload)
    referral = Referral(demographics=_parse_demographics(payload), identifiers=_parse_identifiers(payload))
    return ParsedReferral(
        referral_key=str(referral_key),
        triggering_event_id=str(event_id),
        effective_at=effective_at,
        referral=referral,
    )


def _safe_event_id(envelope: Mapping[str, object]) -> str:
    """`event_id` only, defensively — the one field this module will log before the envelope has
    even been validated. Never touches `payload`."""
    event_id = envelope.get("event_id")
    return str(event_id) if event_id is not None else "<unknown>"


def build_handler(
    *,
    lookup: CandidateLookup,
    client: PulseCoreClient,
    conn: psycopg.Connection,
    person_key_factory: PersonKeyFactory = default_person_key,
) -> ConsumerHandler:
    """The composition root: one `ConsumerHandler` closed over this process's lookup, client, and
    ledger connection. `lookup` and `client` are the same instances the resolver acts through, so a
    `Match`'s "already held" check and the commands it declares read/write against one consistent
    view (design decision 4/5); `conn` backs `resolver.quarantine`'s two ledger effects only.
    """

    def handle(envelope: Mapping[str, object]) -> None:
        event_id = _safe_event_id(envelope)
        try:
            parsed = parse_referral_envelope(envelope)
        except ReferralEnvelopeError:
            logger.exception("malformed referral.received envelope (event_id=%s)", event_id)
            raise

        try:
            decision = resolve(parsed.referral, lookup)
            if isinstance(decision, Ambiguous):
                resolver_quarantine(
                    decision,
                    referral_key=parsed.referral_key,
                    triggering_event_id=parsed.triggering_event_id,
                    effective_at=parsed.effective_at,
                    conn=conn,
                )
            else:
                resolver_act(
                    decision,
                    parsed.referral,
                    referral_key=parsed.referral_key,
                    triggering_event_id=parsed.triggering_event_id,
                    effective_at=parsed.effective_at,
                    lookup=lookup,
                    client=client,
                    person_key_factory=person_key_factory,
                )
        except Exception:
            # Flagged path (a), design decision 3: event_id + subject key only — never the
            # envelope. `parsed.referral_key` is a pseudonymous key, not PHI.
            logger.exception("referral resolution failed (event_id=%s, subject_key=%s)", event_id, parsed.referral_key)
            raise

    return handle


def consume_referrals(
    *,
    queue_url: str,
    lookup: CandidateLookup,
    client: PulseCoreClient,
    conn: psycopg.Connection,
    person_key_factory: PersonKeyFactory = default_person_key,
    sqs_client: object = None,
    deduper: Deduper | None = None,
    max_messages: int = 10,
    wait_time_seconds: int = 20,
    error_backoff_seconds: float = 5.0,
    sleep: Sleeper | None = None,
    iterations: int | None = None,
) -> None:
    """Run the composition-root handler through `pulse_core.client.consume`'s receive/process/
    delete loop. `iterations` bounds a test run; production wiring (`main()`) leaves it `None`
    to run forever. `sleep` left `None` inherits `consume`'s own real-time default — this module
    never re-imports `pulse_core.client`'s private default sleeper."""
    handler = build_handler(lookup=lookup, client=client, conn=conn, person_key_factory=person_key_factory)
    sleep_kwargs: dict[str, Sleeper] = {} if sleep is None else {"sleep": sleep}
    consume(
        handler,
        queue_url=queue_url,
        sqs_client=sqs_client,
        deduper=deduper,
        max_messages=max_messages,
        wait_time_seconds=wait_time_seconds,
        error_backoff_seconds=error_backoff_seconds,
        iterations=iterations,
        **sleep_kwargs,
    )


# --- Production wiring: environment variables only, never a literal (D15) ---------------------

DATABASE_URL_ENV_VAR = "DATABASE_URL"
PULSE_CORE_BASE_URL_ENV_VAR = "PULSE_CORE_BASE_URL"
PULSE_CORE_TOKEN_ENV_VAR = "IDENTITY_SERVICE_TOKEN"  # noqa: S105 — an env var *name*, not a credential
REFERRAL_QUEUE_URL_ENV_VAR = "IDENTITY_REFERRAL_QUEUE_URL"
WRITER_ID = "identity-service"


def main() -> None:  # pragma: no cover — production wiring only; needs a live ledger + command API
    """The runnable production entrypoint: real Postgres connection, real `PulseCoreClient`, real
    SQS — everything this package's tests fake at the module boundary (`schedules.cli`'s
    `_ledger_connection_from_env`/`_pulse_core_client_from_env` follow the identical convention)."""
    import os

    conn = psycopg.connect(os.environ[DATABASE_URL_ENV_VAR])
    client = PulseCoreClient(
        os.environ[PULSE_CORE_BASE_URL_ENV_VAR],
        writer_id=WRITER_ID,
        token=os.environ[PULSE_CORE_TOKEN_ENV_VAR],
    )
    consume_referrals(
        queue_url=os.environ[REFERRAL_QUEUE_URL_ENV_VAR],
        lookup=LedgerLookup(conn),
        client=client,
        conn=conn,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
