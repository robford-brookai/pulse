"""Auth and attribution (pulse-ledger-core design decision 8; runtime-readiness D15).

Two credential paths, and only two:

- **Internal writers** (verdict relay, scheduler, identity resolution, pocar relay) present a
  per-writer bearer token. The server resolves it to a `Writer` and *that* is where the event's
  actor comes from. The request body has no say: a body carrying any credential-derived field is
  rejected, whoever it names. One documented behaviour, no mode switch — the command-api spec's
  scenario offers "rejected or committed as the credential's actor", and rejecting is the choice
  a writer can notice and fix, where a silent overwrite hides a misconfigured producer forever.
- **The Twenty webhook** (D8) is signed, not bearer-authenticated: a shared secret, an HMAC over
  `{version}:{timestamp}:{body}`, and a freshness window so a captured request cannot be replayed
  tomorrow. `verify_signature` is the whole middleware; the route it guards ships disabled
  (`TwentyWebhookConfig`, off unless the environment says otherwise) and turns on in S2.

Credential *values* live in the environment and nowhere else — not in code, not in fixtures, not
in logs. Every error type here is written so its message names the writer or the field at fault
and never the token, the signature, or the request body: an auth failure is exactly when something
gets logged, and a token in a log line is a credential leak. Bodies stay out of these messages for
the same reason PHI stays out of the ledger's logs — once C1 clears, a webhook body is patient
data.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: One variable per writer, holding that writer's token. The suffix is the writer id:
#: `PULSE_LEDGER_WRITER_TOKEN_VERDICT_RELAY` is `verdict-relay`. Naming the writer in the variable
#: rather than in a config file is what keeps the value out of the repository.
WRITER_TOKEN_PREFIX = "PULSE_LEDGER_WRITER_TOKEN_"  # noqa: S105 — a variable name, not a secret

#: Optional, same suffix convention: the authority the writer declares under, stamped on the
#: event as `actor_authority`.
WRITER_AUTHORITY_PREFIX = "PULSE_LEDGER_WRITER_AUTHORITY_"

TWENTY_WEBHOOK_ENABLED_ENV = "PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED"
TWENTY_WEBHOOK_SECRET_ENV = "PULSE_LEDGER_TWENTY_WEBHOOK_SECRET"  # noqa: S105 — a variable name, not a secret

#: The second accepted secret, set for the length of a D15 quarterly rotation: add the incoming
#: secret here, re-point Twenty at it, then promote it into `TWENTY_WEBHOOK_SECRET_ENV` and delete
#: this one. Both are accepted meanwhile, so no correctly signed drag is rejected in the window.
TWENTY_WEBHOOK_SECRET_NEXT_ENV = "PULSE_LEDGER_TWENTY_WEBHOOK_SECRET_NEXT"  # noqa: S105 — a variable name, not a secret

#: A bearer credential shorter than this is a placeholder someone forgot to replace. Refusing it
#: at boot beats discovering `changeme` in a production environment by reading the logs.
MIN_TOKEN_LENGTH = 32

#: Every internal writer authenticates as a service, so its actor_type is fixed. Human and agent
#: actors reach the ledger through the Twenty path, which is a different credential and a
#: different (still disabled) route.
INTERNAL_ACTOR_TYPE = "system"

#: The one writer identity permitted to declare the backfill-only vocabulary
#: (`backfill_genesis`, `reconstruction_gap` — command-api spec "Backfill mode is the same path
#: with a restricted vocabulary", task 3.5). Configured like any other writer, via
#: `PULSE_LEDGER_WRITER_TOKEN_BACKFILL`.
BACKFILL_ACTOR_ID = "backfill"

#: The fields a credential decides. A body may not carry them — see `Writer.attribute`.
CREDENTIAL_DERIVED_FIELDS = ("actor_type", "actor_id", "actor_authority", "producer")

SIGNATURE_VERSION = "v1"
SIGNATURE_HEADER = "X-Pulse-Signature"
TIMESTAMP_HEADER = "X-Pulse-Timestamp"
SIGNATURE_FRESHNESS = timedelta(minutes=5)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


class AuthenticationError(Exception):
    """The caller did not prove who it is. Maps to 401.

    `challenge` is the `WWW-Authenticate` value the 401 carries. It lives on the exception rather
    than on the handler because the two auth paths want different challenges and only the
    exception knows which path raised it.
    """

    challenge = "Bearer"


class MissingCredentialError(AuthenticationError):
    """No Authorization header at all."""

    def __init__(self) -> None:
        super().__init__("an Authorization header is required")


class MalformedAuthorizationHeaderError(AuthenticationError):
    """An Authorization header that is not a single bearer token."""

    def __init__(self) -> None:
        super().__init__("Authorization must be 'Bearer <token>'")


class UnknownCredentialError(AuthenticationError):
    """A well-formed token that belongs to no configured writer."""

    def __init__(self) -> None:
        super().__init__("the presented credential is not a known writer credential")


class SignatureError(AuthenticationError):
    """A signed request whose signature the server will not accept."""

    challenge = f'Signature headers="{TIMESTAMP_HEADER} {SIGNATURE_HEADER}"'


class InvalidSignatureError(SignatureError):
    def __init__(self) -> None:
        super().__init__("signature does not match")


class StaleSignatureError(SignatureError):
    def __init__(self) -> None:
        super().__init__(
            f"signature timestamp is missing, unreadable, or outside the "
            f"{int(SIGNATURE_FRESHNESS.total_seconds())}s freshness window"
        )


class ActorSpoofError(Exception):
    """A body tried to say who the actor is. Maps to 403 — authenticated, but not as that."""

    def __init__(self, field: str, writer_id: str, claimed: object) -> None:
        self.field = field
        self.writer_id = writer_id
        self.claimed = claimed
        super().__init__(
            f"{field!r} is derived from the credential and must not be supplied by a writer; "
            f"{writer_id!r} claimed {claimed!r}"
        )


class CredentialConfigurationError(Exception):
    """The service is misconfigured. Raised at boot, never in response to a request."""


class NoCredentialsConfiguredError(CredentialConfigurationError):
    def __init__(self) -> None:
        super().__init__(f"no writer credentials in the environment; set at least one {WRITER_TOKEN_PREFIX}<WRITER_ID>")


class DuplicateCredentialError(CredentialConfigurationError):
    """Two writers share a token, so attribution would be a coin flip."""

    def __init__(self, writer_ids: tuple[str, ...]) -> None:
        self.writer_ids = writer_ids
        super().__init__(f"writers {list(writer_ids)} share one credential; attribution would be ambiguous")


class WeakCredentialError(CredentialConfigurationError):
    def __init__(self, writer_id: str) -> None:
        self.writer_id = writer_id
        super().__init__(f"the credential for {writer_id!r} is shorter than {MIN_TOKEN_LENGTH} characters")


class TwentyWebhookSecretMissingError(CredentialConfigurationError):
    def __init__(self) -> None:
        super().__init__(
            f"{TWENTY_WEBHOOK_ENABLED_ENV} is set but neither {TWENTY_WEBHOOK_SECRET_ENV} nor "
            f"{TWENTY_WEBHOOK_SECRET_NEXT_ENV} is"
        )


class TwentyWebhookBlankSecretError(CredentialConfigurationError):
    """A secret variable is set to whitespace or the empty string.

    Refused rather than read as "unset": treating a blank value as absent would silently run half
    a rotation on whichever secret happened to be non-blank, and leave a route enabled by a value
    nobody set. The variable name is named; the value never is.
    """

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"{variable} is set to a blank value; unset it or give it the secret")


@dataclass(frozen=True)
class Writer:
    """An authenticated internal writer, and the attribution it may declare under."""

    writer_id: str
    actor_type: str = INTERNAL_ACTOR_TYPE
    actor_authority: str | None = None

    @property
    def actor_id(self) -> str:
        """D15 in one line: the actor is the writer, always."""
        return self.writer_id

    def attribution(self) -> dict[str, object]:
        return {
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "actor_authority": self.actor_authority,
            "producer": self.writer_id,
        }

    def attribute(self, body: Mapping[str, object]) -> dict[str, object]:
        """Return the body with this writer's attribution stamped on it.

        Raises `ActorSpoofError` if the body carries any credential-derived field — including one
        that happens to agree with the credential, so there is a single rule to state and a single
        rule to test rather than a value comparison whose edge cases multiply.
        """
        for field_name in CREDENTIAL_DERIVED_FIELDS:
            if field_name in body:
                raise ActorSpoofError(field_name, self.writer_id, body[field_name])
        return {**body, **self.attribution()}


def _writer_id_from_suffix(suffix: str) -> str:
    return suffix.lower().replace("_", "-")


class CredentialRegistry:
    """The configured writers, looked up by the token they present.

    Lookup is by SHA-256 digest rather than by comparing token strings: a dict hit on a digest
    costs the same whichever writer it finds and whether or not it finds one, so the lookup does
    not leak a prefix of a valid token through its timing.
    """

    def __init__(self, writers: Mapping[str, Writer], digests: Mapping[str, str]) -> None:
        self._writers = dict(writers)
        self._digests = dict(digests)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> CredentialRegistry:
        """Build the registry from `PULSE_LEDGER_WRITER_TOKEN_*` / `..._AUTHORITY_*` variables.

        Raises `CredentialConfigurationError` rather than returning a registry that would
        authenticate nobody, authenticate ambiguously, or accept a placeholder token.
        """
        authorities = {
            _writer_id_from_suffix(name.removeprefix(WRITER_AUTHORITY_PREFIX)): value
            for name, value in environ.items()
            if name.startswith(WRITER_AUTHORITY_PREFIX)
        }
        writers: dict[str, Writer] = {}
        digests: dict[str, str] = {}
        for name in sorted(environ):
            if not name.startswith(WRITER_TOKEN_PREFIX):
                continue
            writer_id = _writer_id_from_suffix(name.removeprefix(WRITER_TOKEN_PREFIX))
            token = environ[name]
            if len(token) < MIN_TOKEN_LENGTH:
                raise WeakCredentialError(writer_id)
            digest = _digest(token)
            if digest in digests:
                raise DuplicateCredentialError((digests[digest], writer_id))
            digests[digest] = writer_id
            writers[writer_id] = Writer(
                writer_id=writer_id,
                actor_type=INTERNAL_ACTOR_TYPE,
                actor_authority=authorities.get(writer_id),
            )
        if not writers:
            raise NoCredentialsConfiguredError()
        return cls(writers, digests)

    @property
    def writer_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._writers))

    def resolve(self, token: str) -> Writer:
        """The writer that owns this token. Raises `UnknownCredentialError` if none does."""
        writer_id = self._digests.get(_digest(token))
        if writer_id is None:
            raise UnknownCredentialError()
        return self._writers[writer_id]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_token(header: str | None) -> str:
    """Pull the token out of an `Authorization: Bearer <token>` header value."""
    if header is None:
        raise MissingCredentialError()
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        raise MalformedAuthorizationHeaderError()
    return token


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The signature a Twenty webhook is expected to carry, `{version}={hex}`."""
    message = f"{SIGNATURE_VERSION}:{timestamp}:".encode() + body
    return f"{SIGNATURE_VERSION}={hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()}"


def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    *,
    now: datetime,
    freshness: timedelta = SIGNATURE_FRESHNESS,
) -> None:
    """Verify a signed request, or raise. Freshness is checked before the HMAC.

    `now` is passed in rather than read from the clock so the window is testable without
    monkeypatching time.
    """
    if not _is_fresh(timestamp, now=now, freshness=freshness):
        raise StaleSignatureError()
    assert timestamp is not None  # noqa: S101 — narrowed by _is_fresh, which rejects None
    expected = sign(secret, timestamp, body)
    if signature is None or not hmac.compare_digest(expected, signature):
        raise InvalidSignatureError()


def _is_fresh(timestamp: str | None, *, now: datetime, freshness: timedelta) -> bool:
    if timestamp is None:
        return False
    try:
        signed_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError):
        return False
    return abs(now - signed_at) <= freshness


@dataclass(frozen=True)
class TwentyWebhookConfig:
    """Whether the D8 kanban ingress route exists, and the secrets guarding it if it does.

    Enabled-with-no-secret is a boot failure, not an unauthenticated route — and the check lives
    in `__post_init__` rather than in `from_env`, so the invariant holds however the config is
    built and the route can call `verify` without re-proving it.

    Two secrets are accepted so D15's quarterly rotation has no window of rejected drags: set
    `secret_next`, re-point Twenty, then promote it into `secret` and unset it. Neither secret
    changes the signing recipe, the headers, or the freshness window — `verify` is `verify_signature`
    tried against each configured value.
    """

    enabled: bool = False
    secret: str | None = None
    secret_next: str | None = None

    def __post_init__(self) -> None:
        for variable, value in (
            (TWENTY_WEBHOOK_SECRET_ENV, self.secret),
            (TWENTY_WEBHOOK_SECRET_NEXT_ENV, self.secret_next),
        ):
            if value is not None and not value.strip():
                raise TwentyWebhookBlankSecretError(variable)
        if self.enabled and not self.accepted_secrets:
            raise TwentyWebhookSecretMissingError()

    @property
    def accepted_secrets(self) -> tuple[str, ...]:
        """Every configured secret, current first. Empty only when the route is disabled."""
        return tuple(value for value in (self.secret, self.secret_next) if value is not None)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> TwentyWebhookConfig:
        return cls(
            enabled=environ.get(TWENTY_WEBHOOK_ENABLED_ENV, "").strip().lower() in _TRUTHY,
            secret=environ.get(TWENTY_WEBHOOK_SECRET_ENV),
            secret_next=environ.get(TWENTY_WEBHOOK_SECRET_NEXT_ENV),
        )

    def verify(
        self,
        body: bytes,
        timestamp: str | None,
        signature: str | None,
        *,
        now: datetime,
        freshness: timedelta = SIGNATURE_FRESHNESS,
    ) -> None:
        """Accept a signature valid under any configured secret, or raise.

        Every configured secret is checked — no early exit on the first match — so the time this
        takes does not say *which* secret a request was signed with. Each individual check is the
        unchanged `verify_signature`, so each HMAC comparison is still constant-time and freshness
        is still decided before any HMAC (a stale timestamp raises from the first check, and the
        answer would be identical for the second). With no secret configured nothing verifies:
        a misconstructed config fails closed rather than open.
        """
        matched = False
        for secret in self.accepted_secrets:
            try:
                verify_signature(secret, body, timestamp, signature, now=now, freshness=freshness)
            except InvalidSignatureError:
                continue
            matched = True
        if not matched:
            raise InvalidSignatureError()
