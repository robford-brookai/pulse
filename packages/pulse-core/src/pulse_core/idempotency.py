"""Idempotency key derivation — D16, client side.

The key is `{writer_id}:{sha256(subject, command_type, payload, logical_time)}`, unique-constrained
in the ledger for the ledger's lifetime. The ledger answers a repeat of a key with the original
event id and writes nothing; a distinct fact must therefore never derive an existing key, and the
same fact must always derive the same one — from any writer process, in any interpreter, in any
order its payload happened to be built.

Three choices carry that:

- **The pre-image is a JSON document, not concatenated text.** `sha256("referral" + "a:b" + ...)`
  cannot tell `subject_key="a:b"` from `subject_type="referral:a"`; a JSON object with named
  members has no delimiter to smear.
- **Serialisation is canonical**: keys sorted at every depth, no insignificant whitespace,
  ASCII-escaped so the byte string does not depend on the caller's encoding. Two processes that
  built the same payload dict in different orders derive one key.
- **Only JSON-native payload values are accepted.** A `datetime` has no single spelling, so
  serialising one here would mint a format per caller and split the key space the first time a
  writer serialised it differently. The payload crosses the wire as JSON anyway: it is already
  serialised by the time it is a command, and the error names the offending path so the caller can
  fix it at the source.

`logical_time` is the writer's own clock for the fact, which is what makes two genuine
observations distinct rather than a replay. An aware `datetime` is normalised to UTC, so the same
instant in two offsets is one key. A writer whose logical clock is already a string may pass it
through verbatim.

The digest is one-way, so a key is safe to log and store even once payloads carry PHI (C1) — and
the payload must never be logged alongside it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

#: Separates the writer from the digest. A `writer_id` may not contain it.
KEY_SEPARATOR = ":"


class IdempotencyKeyError(ValueError):
    """A key cannot be derived from what the caller supplied."""


class WriterIdError(IdempotencyKeyError):
    """The writer id is empty or would make the key's two halves ambiguous."""

    def __init__(self, writer_id: str) -> None:
        self.writer_id = writer_id
        super().__init__(
            f"writer_id {writer_id!r} must be non-blank and must not contain {KEY_SEPARATOR!r}, "
            "which separates the writer from the digest"
        )


class NaiveLogicalTimeError(IdempotencyKeyError):
    """The logical time arrived without a timezone, so its instant is not determined."""

    def __init__(self) -> None:
        super().__init__("logical_time must be timezone-aware; a naive timestamp has no determined instant")


class UnhashablePayloadError(IdempotencyKeyError):
    """A payload value has no canonical JSON spelling, so no stable key can be derived from it.

    Carries the path to the value and its type — never the value, which may be PHI. The path is
    made of payload *keys*, which are field names in every command the catalog generates; a caller
    that keyed a payload by an identifier instead would put that identifier in this message.
    """

    def __init__(self, path: str, type_name: str) -> None:
        self.path = path
        self.type_name = type_name
        super().__init__(
            f"{path} is a {type_name}, which has no canonical JSON spelling; "
            "serialise it in the payload the writer sends, so every writer spells it the same way"
        )


def derive_idempotency_key(
    *,
    writer_id: str,
    subject_type: str,
    subject_key: str,
    command_type: str,
    payload: Mapping[str, object],
    logical_time: datetime | str,
) -> str:
    """Derive the D16 idempotency key for one command.

    Raises `WriterIdError`, `NaiveLogicalTimeError` or `UnhashablePayloadError` — all
    `IdempotencyKeyError` — rather than deriving a key that a second caller could not reproduce.
    """
    if not writer_id.strip() or KEY_SEPARATOR in writer_id:
        raise WriterIdError(writer_id)
    fact = {
        "subject_type": subject_type,
        "subject_key": subject_key,
        "command_type": command_type,
        "logical_time": _canonical_logical_time(logical_time),
        "payload": _canonical(payload, "payload"),
    }
    pre_image = json.dumps(fact, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(pre_image.encode("utf-8")).hexdigest()
    return f"{writer_id}{KEY_SEPARATOR}{digest}"


def _canonical_logical_time(logical_time: datetime | str) -> str:
    if isinstance(logical_time, str):
        return logical_time
    if logical_time.tzinfo is None or logical_time.tzinfo.utcoffset(logical_time) is None:
        raise NaiveLogicalTimeError()
    return logical_time.astimezone(timezone.utc).isoformat()


def _canonical(value: object, path: str) -> object:
    """The value as canonical JSON data, or `UnhashablePayloadError` naming where it is not.

    `str`/`bytes` are excluded from the `Sequence` branch explicitly, being sequences themselves.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # NaN and the infinities have no JSON spelling. `allow_nan=False` would raise on them
        # later anyway, but with no path to the value that caused it.
        if not math.isfinite(value):
            raise UnhashablePayloadError(path, "non-finite float")
        return value
    if isinstance(value, Mapping):
        canonical: dict[str, object] = {}
        for key, member in value.items():
            if not isinstance(key, str):
                raise UnhashablePayloadError(path, f"mapping with a {type(key).__name__} key")
            canonical[key] = _canonical(member, f"{path}.{key}")
        return canonical
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(member, f"{path}[{index}]") for index, member in enumerate(value)]
    raise UnhashablePayloadError(path, type(value).__name__)
