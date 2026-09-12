"""Canonical request v1 and the authenticated writer binding — the D16 amendment's definitions.

D16 as shipped answers a repeated idempotency key with the original commit's result, looked up
globally by the key's text alone. Two things that text cannot carry are therefore trusted: *who*
sent the original command (the prefix before the colon is client-supplied, not authenticated) and
*what* they sent (the digest is the SDK's, over a client-only `logical_time` the server never
receives). This module supplies both as first-class values, so the commit path can require them to
match before it replays anything (the amendment proposed in ADR-0007, design decision 1).

**The fingerprint is over the accepted semantic request, not over the bytes.** A retry that spells
the same instant `Z` instead of `+00:00`, or builds its JSON object in another order, is the same
request and must still replay — that compatibility is the acceptance criterion for the whole change
(design §5). So `canonical_request` normalises the spellings that carry no meaning and preserves
every one that does: list order is semantic, a string is not its number, and a `null` member is not
an absent one.

**What is deliberately *not* in it** (`EXCLUDED_FIELDS_V1`):

- `logical_time` — the SDK's clock for the fact. It is hashed into the key and need not equal
  `effective_at`, so reconstructing it server-side would mint a value the client never sent and
  break the valid retries this change exists to protect (design decision 2, non-goals).
- `idempotency_key` and the credential — the key addresses this record, and identity is the
  binding's other half; hashing either would make the fingerprint self-referential or
  credential-derived.
- `actor_type`, `actor_id`, `actor_authority`, `producer` — credential-derived at the boundary
  (`Writer.attribute`). They are the writer identity, held beside the fingerprint rather than
  inside it, which is what lets one request under two principals be recognised as one request
  claimed by different writers rather than as two unrelated digests.
- `recorded_at`, `rule_version`, `event_id` — the server's, not the request's. A retry days later
  must fingerprint identically.
- `correlation_id`, `causation_id` — transport-only tracing. Two retries of one fact routinely
  carry fresh trace ids, and a conflict on them would be a false positive in the worst place.

**Versioning.** The field map is frozen under `v1` and the version string is hashed into the
pre-image, so a v1 digest cannot be relabelled as another version's. A change to the field set
adds a version beside v1; it never edits v1, because every binding already stored was computed
under the old map. `request_fingerprint` returns `"{version}:{sha256}"` so the stored value carries
what produced it.

**PHI.** The fingerprint is derived from `payload` and `evidence`, which carry PHI once C1 clears,
so it is *not* safe to log even though it is a digest — a digest of a small value space is a lookup
table. `WriterBinding` keeps it out of its repr and out of `telemetry_fields`, and the error for an
unfingerprintable value names the path and the type, never the value (the same posture
`pulse_core.idempotency.UnhashablePayloadError` takes).
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from pulse_ledger.auth import Writer
from pulse_ledger.commit import Declaration

#: The version of the canonical field map below. Stored beside every binding and hashed into every
#: digest; a field-set change requires a new one.
FINGERPRINT_VERSION = "v1"

#: The accepted semantic request, in the order the pre-image names them. The tuple is the contract:
#: `tests/test_request_fingerprint.py` asserts it verbatim, so widening it fails there first.
CANONICAL_FIELDS_V1: tuple[str, ...] = (
    "subject_type",
    "subject_key",
    "event_type",
    "to_state",
    "effective_at",
    "epoch",
    "evidence_class",
    "evidence",
    "evidence_bounds",
    "payload",
)

#: Named exclusions, so "absent from v1" is a decision on the record rather than an omission.
#: `logical_time` is not a `Declaration` field at all — it is named here because the SDK hashes it
#: and the non-goal of reconstructing it is the reason this map looks the way it does.
EXCLUDED_FIELDS_V1 = frozenset({
    "logical_time",
    "idempotency_key",
    "actor_type",
    "actor_id",
    "actor_authority",
    "producer",
    "recorded_at",
    "rule_version",
    "event_id",
    "correlation_id",
    "causation_id",
})

#: Separates the version from the digest in a fingerprint's stored spelling.
VERSION_SEPARATOR = ":"


class FingerprintError(ValueError):
    """A canonical request cannot be computed from what the boundary accepted."""


class UnknownFingerprintVersionError(FingerprintError):
    """A version this build has no field map for — refused rather than computed under v1."""

    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(f"no canonical request field map for fingerprint version {version!r}")


class UnfingerprintableValueError(FingerprintError):
    """A request value has no canonical spelling, so no stable fingerprint exists for it.

    Names the path and the type, never the value: `payload` and `evidence` are the two PHI-bearing
    fields, and this message reaches an error response and a log.
    """

    def __init__(self, path: str, type_name: str) -> None:
        self.path = path
        self.type_name = type_name
        super().__init__(f"{path} is a {type_name}, which has no canonical spelling for a request fingerprint")


def canonical_request(declaration: Declaration, *, version: str = FINGERPRINT_VERSION) -> dict[str, object]:
    """The accepted request as the versioned field map sees it.

    Returned rather than hashed directly so the map is inspectable — by tests, and by the legacy
    reconstruction path (task 2.2), which has to build this same shape from a stored event.
    """
    if version != FINGERPRINT_VERSION:
        raise UnknownFingerprintVersionError(version)
    canonical: dict[str, object] = {"fingerprint_version": version}
    for name in CANONICAL_FIELDS_V1:
        canonical[name] = _canonical_value(getattr(declaration, name), name)
    return canonical


def request_fingerprint(declaration: Declaration, *, version: str = FINGERPRINT_VERSION) -> str:
    """The versioned fingerprint of one accepted request: `"{version}:{sha256}"`.

    Never log the result: it is derived from `payload` and `evidence` (module docstring).
    """
    canonical = canonical_request(declaration, version=version)
    pre_image = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(pre_image.encode("utf-8")).hexdigest()
    return f"{version}{VERSION_SEPARATOR}{digest}"


class BindingDisposition(str, Enum):
    """What an incoming request may do with an idempotency key, given the binding on record.

    `CONFLICT` is deliberately one value for every mismatch — a different writer and a different
    request are told apart in the ledger, never in the response, which would let a caller probe
    what the key already holds (design decision 3).
    """

    UNCLAIMED = "unclaimed"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class WriterBinding:
    """The authenticated claim on one idempotency key.

    `fingerprint` is kept out of the generated repr for the reason the module docstring gives, the
    same way `Declaration` keeps `payload` and `evidence` out of its own.
    """

    idempotency_key: str
    writer_id: str
    fingerprint: str = field(repr=False)
    event_id: uuid.UUID | None = None

    @property
    def fingerprint_version(self) -> str:
        """The version the stored fingerprint was computed under — its own prefix, not this build's."""
        return self.fingerprint.partition(VERSION_SEPARATOR)[0]

    def telemetry_fields(self) -> dict[str, object]:
        """The facts a log line may carry about this binding.

        The key is a one-way digest of the writer's own choosing and the event id is already public
        in every response, so both are safe; the fingerprint is not, and is absent by construction
        rather than by a caller remembering to drop it.
        """
        return {
            "idempotency_key": self.idempotency_key,
            "writer_id": self.writer_id,
            "fingerprint_version": self.fingerprint_version,
            "event_id": self.event_id,
        }


def bind_request(
    *,
    idempotency_key: str,
    writer: Writer,
    declaration: Declaration,
    event_id: uuid.UUID | None = None,
    version: str = FINGERPRINT_VERSION,
) -> WriterBinding:
    """The binding for one authenticated command at the API boundary.

    The writer comes from the resolved credential — the bearer `Writer`, the batch route's single
    credential, or the fixed `api.WEBHOOK_WRITER` principal for signed Twenty ingress. The text
    before the colon in `idempotency_key` is never consulted: a client may spell any prefix it
    likes, and D15's "attribution is authentication" says that spelling establishes nothing.
    """
    return WriterBinding(
        idempotency_key=idempotency_key,
        writer_id=writer.writer_id,
        fingerprint=request_fingerprint(declaration, version=version),
        event_id=event_id,
    )


def classify_binding(existing: WriterBinding | None, *, writer_id: str, fingerprint: str) -> BindingDisposition:
    """What this request may do with the key, given the binding already on record.

    A replay requires both halves to agree: the same authenticated writer *and* the same versioned
    fingerprint. A fingerprint stored under another version can never match, because a v1 digest and
    a v2 digest of the same request are different strings — comparison is exact, so an old binding
    conflicts rather than being re-derived under the current map.
    """
    if existing is None:
        return BindingDisposition.UNCLAIMED
    if existing.writer_id == writer_id and existing.fingerprint == fingerprint:
        return BindingDisposition.REPLAY
    return BindingDisposition.CONFLICT


def _canonical_value(value: object, path: str) -> object:
    """One request value as canonical JSON data, or `UnfingerprintableValueError` naming where not.

    Deliberately more permissive than `pulse_core.idempotency`, which refuses a `datetime` outright
    so that two writer processes cannot mint two spellings of one instant. Here the spelling has
    already been chosen — this runs server-side on a request the boundary accepted, and the webhook
    mapping builds declarations in-process with real `datetime` and `UUID` values — so normalising
    is the behaviour that keeps a valid retry replaying. Anything without a single spelling still
    raises.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # NaN and the infinities have no JSON spelling; `allow_nan=False` would raise later without
        # naming the path that caused it.
        if not math.isfinite(value):
            raise UnfingerprintableValueError(path, "non-finite float")
        return value
    if isinstance(value, datetime):
        return _canonical_instant(value, path)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        canonical: dict[str, object] = {}
        for key, member in value.items():
            if not isinstance(key, str):
                raise UnfingerprintableValueError(path, f"mapping with a {type(key).__name__} key")
            canonical[key] = _canonical_value(member, f"{path}.{key}")
        return canonical
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        # Order is preserved: a list of codes in another order is another request.
        return [_canonical_value(member, f"{path}[{index}]") for index, member in enumerate(value)]
    raise UnfingerprintableValueError(path, type(value).__name__)


def _canonical_instant(value: datetime, path: str) -> str:
    """One UTC spelling per instant: `Z`, `-00:00` and `+02:00` all collapse onto `+00:00`.

    A naive datetime cannot reach `effective_at` or `evidence_bounds` (`Declaration.__post_init__`
    refuses it), but a payload member is not checked there, and a fingerprint that assumed UTC for
    one would answer a different fact with the original result.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise UnfingerprintableValueError(path, "naive datetime")
    return value.astimezone(timezone.utc).isoformat()
