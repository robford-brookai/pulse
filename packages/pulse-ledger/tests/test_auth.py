"""Auth and attribution: credentials resolve to writers, and a writer can only be itself.

Credential *values* are generated per test and pushed through the environment, never written
into a fixture — the same posture the S1 work orders require of every writer service ("credential
names in Context, values from the environment, never in code or fixtures").
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from pulse_ledger.auth import (
    MIN_TOKEN_LENGTH,
    SIGNATURE_VERSION,
    TWENTY_WEBHOOK_ENABLED_ENV,
    TWENTY_WEBHOOK_SECRET_ENV,
    TWENTY_WEBHOOK_SECRET_NEXT_ENV,
    WRITER_AUTHORITY_PREFIX,
    WRITER_TOKEN_PREFIX,
    ActorSpoofError,
    CredentialRegistry,
    DuplicateCredentialError,
    InvalidSignatureError,
    MalformedAuthorizationHeaderError,
    MissingCredentialError,
    NoCredentialsConfiguredError,
    StaleSignatureError,
    TwentyWebhookBlankSecretError,
    TwentyWebhookConfig,
    TwentyWebhookSecretMissingError,
    UnknownCredentialError,
    WeakCredentialError,
    Writer,
    bearer_token,
    sign,
    verify_signature,
)


def _token() -> str:
    """A credential value that exists only for the life of one test."""
    return secrets.token_urlsafe(32)


@pytest.fixture
def relay_token() -> str:
    return _token()


@pytest.fixture
def env(relay_token: str) -> dict[str, str]:
    return {f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": relay_token}


class TestRegistryFromEnv:
    def test_writer_id_comes_from_the_variable_name(self, env: dict[str, str]) -> None:
        registry = CredentialRegistry.from_env(env)
        assert registry.writer_ids == ("verdict-relay",)

    def test_a_token_resolves_to_its_writer(self, env: dict[str, str], relay_token: str) -> None:
        writer = CredentialRegistry.from_env(env).resolve(relay_token)
        assert writer == Writer(writer_id="verdict-relay", actor_type="system", actor_authority=None)

    def test_authority_is_read_from_its_own_variable(self, env: dict[str, str], relay_token: str) -> None:
        env[f"{WRITER_AUTHORITY_PREFIX}VERDICT_RELAY"] = "verdict-publication"
        writer = CredentialRegistry.from_env(env).resolve(relay_token)
        assert writer.actor_authority == "verdict-publication"

    def test_unrelated_variables_are_ignored(self, env: dict[str, str]) -> None:
        env["PATH"] = "/usr/bin"
        env["PULSE_LEDGER_DATABASE_URL"] = "postgresql:///ledger"
        assert CredentialRegistry.from_env(env).writer_ids == ("verdict-relay",)

    def test_writer_ids_are_sorted(self) -> None:
        env = {
            f"{WRITER_TOKEN_PREFIX}SCHEDULER": _token(),
            f"{WRITER_TOKEN_PREFIX}IDENTITY_RESOLUTION": _token(),
            f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": _token(),
        }
        assert CredentialRegistry.from_env(env).writer_ids == (
            "identity-resolution",
            "scheduler",
            "verdict-relay",
        )

    def test_an_authority_without_a_token_is_refused(self) -> None:
        env = {f"{WRITER_AUTHORITY_PREFIX}GHOST_WRITER": "anything"}
        with pytest.raises(NoCredentialsConfiguredError):
            CredentialRegistry.from_env(env)

    def test_two_writers_sharing_a_token_is_refused(self, relay_token: str) -> None:
        env = {
            f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": relay_token,
            f"{WRITER_TOKEN_PREFIX}SCHEDULER": relay_token,
        }
        with pytest.raises(DuplicateCredentialError) as exc:
            CredentialRegistry.from_env(env)
        assert relay_token not in str(exc.value)

    def test_a_short_token_is_refused(self) -> None:
        env = {f"{WRITER_TOKEN_PREFIX}VERDICT_RELAY": "changeme"}
        with pytest.raises(WeakCredentialError) as exc:
            CredentialRegistry.from_env(env)
        assert "changeme" not in str(exc.value)
        assert str(MIN_TOKEN_LENGTH) in str(exc.value)

    def test_an_empty_environment_is_refused(self) -> None:
        with pytest.raises(NoCredentialsConfiguredError):
            CredentialRegistry.from_env({})


class TestResolve:
    def test_an_unknown_token_is_rejected(self, env: dict[str, str]) -> None:
        registry = CredentialRegistry.from_env(env)
        with pytest.raises(UnknownCredentialError):
            registry.resolve(_token())

    def test_the_rejection_never_echoes_the_token(self, env: dict[str, str]) -> None:
        presented = _token()
        registry = CredentialRegistry.from_env(env)
        with pytest.raises(UnknownCredentialError) as exc:
            registry.resolve(presented)
        assert presented not in str(exc.value)

    def test_an_empty_token_is_rejected(self, env: dict[str, str]) -> None:
        with pytest.raises(UnknownCredentialError):
            CredentialRegistry.from_env(env).resolve("")


class TestBearerHeader:
    def test_a_bearer_header_yields_its_token(self) -> None:
        assert bearer_token("Bearer abc123") == "abc123"

    def test_the_scheme_is_case_insensitive(self) -> None:
        assert bearer_token("bearer abc123") == "abc123"

    def test_a_missing_header_is_missing_not_malformed(self) -> None:
        with pytest.raises(MissingCredentialError):
            bearer_token(None)

    @pytest.mark.parametrize("header", ["abc123", "Basic abc123", "Bearer", "Bearer ", "Bearer a b"])
    def test_anything_else_is_malformed(self, header: str) -> None:
        with pytest.raises(MalformedAuthorizationHeaderError) as exc:
            bearer_token(header)
        assert "abc123" not in str(exc.value)


class TestAttribution:
    """D15: the actor is the credential's, and there is no way for a body to say otherwise."""

    writer = Writer(writer_id="verdict-relay", actor_type="system", actor_authority="verdict-publication")

    def test_the_credential_supplies_the_actor(self) -> None:
        attributed = self.writer.attribute({"subject_type": "billing_episode", "to_state": "qualified"})
        assert attributed["actor_type"] == "system"
        assert attributed["actor_id"] == "verdict-relay"
        assert attributed["actor_authority"] == "verdict-publication"
        assert attributed["producer"] == "verdict-relay"

    def test_the_writers_own_fields_survive(self) -> None:
        attributed = self.writer.attribute({"subject_type": "billing_episode", "to_state": "qualified"})
        assert attributed["subject_type"] == "billing_episode"
        assert attributed["to_state"] == "qualified"

    def test_the_body_is_not_mutated(self) -> None:
        body: dict[str, object] = {"to_state": "qualified"}
        self.writer.attribute(body)
        assert body == {"to_state": "qualified"}

    def test_a_body_claiming_another_actor_is_rejected(self) -> None:
        with pytest.raises(ActorSpoofError) as exc:
            self.writer.attribute({"to_state": "qualified", "actor_id": "reconciliation"})
        assert exc.value.field == "actor_id"
        assert exc.value.writer_id == "verdict-relay"
        assert exc.value.claimed == "reconciliation"

    def test_a_body_echoing_its_own_actor_is_rejected_too(self) -> None:
        """One documented behaviour, not two: the body never carries actor fields."""
        with pytest.raises(ActorSpoofError):
            self.writer.attribute({"to_state": "qualified", "actor_id": "verdict-relay"})

    @pytest.mark.parametrize("field", ["actor_type", "actor_id", "actor_authority", "producer"])
    def test_every_credential_derived_field_is_refused(self, field: str) -> None:
        with pytest.raises(ActorSpoofError) as exc:
            self.writer.attribute({"to_state": "qualified", field: "reconciliation"})
        assert exc.value.field == field

    def test_a_null_actor_claim_is_still_a_claim(self) -> None:
        with pytest.raises(ActorSpoofError):
            self.writer.attribute({"to_state": "qualified", "actor_authority": None})


class TestHmacSignatures:
    """The Twenty webhook path (D8/D15). The middleware exists; the route it guards ships off."""

    # Generated, never written down — the same posture the writer credentials above keep.
    secret = _token()
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)

    def test_a_valid_signature_verifies(self) -> None:
        body = b'{"card":"synthetic"}'
        timestamp = str(int(self.now.timestamp()))
        verify_signature(self.secret, body, timestamp, sign(self.secret, timestamp, body), now=self.now)

    def test_the_signature_is_versioned_and_hex(self) -> None:
        timestamp = "1770000000"
        body = b"{}"
        expected = hmac.new(
            self.secret.encode(),
            f"{SIGNATURE_VERSION}:{timestamp}:".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        assert sign(self.secret, timestamp, body) == f"{SIGNATURE_VERSION}={expected}"

    def test_a_tampered_body_fails(self) -> None:
        timestamp = str(int(self.now.timestamp()))
        signature = sign(self.secret, timestamp, b'{"card":"synthetic"}')
        with pytest.raises(InvalidSignatureError):
            verify_signature(self.secret, b'{"card":"tampered"}', timestamp, signature, now=self.now)

    def test_a_signature_for_another_timestamp_fails(self) -> None:
        body = b"{}"
        signature = sign(self.secret, "1770000000", body)
        with pytest.raises(InvalidSignatureError):
            verify_signature(self.secret, body, str(int(self.now.timestamp())), signature, now=self.now)

    def test_another_secret_fails(self) -> None:
        timestamp = str(int(self.now.timestamp()))
        body = b"{}"
        signature = sign(_token(), timestamp, body)
        with pytest.raises(InvalidSignatureError):
            verify_signature(self.secret, body, timestamp, signature, now=self.now)

    @pytest.mark.parametrize("signature", ["", "deadbeef", "v0=deadbeef", "v1=nothex"])
    def test_a_malformed_signature_fails(self, signature: str) -> None:
        with pytest.raises(InvalidSignatureError):
            verify_signature(self.secret, b"{}", str(int(self.now.timestamp())), signature, now=self.now)

    def test_an_old_signature_is_stale(self) -> None:
        stale = self.now - timedelta(minutes=10)
        timestamp = str(int(stale.timestamp()))
        with pytest.raises(StaleSignatureError):
            verify_signature(self.secret, b"{}", timestamp, sign(self.secret, timestamp, b"{}"), now=self.now)

    def test_a_future_signature_is_stale(self) -> None:
        ahead = self.now + timedelta(minutes=10)
        timestamp = str(int(ahead.timestamp()))
        with pytest.raises(StaleSignatureError):
            verify_signature(self.secret, b"{}", timestamp, sign(self.secret, timestamp, b"{}"), now=self.now)

    def test_a_non_numeric_timestamp_is_stale(self) -> None:
        with pytest.raises(StaleSignatureError):
            verify_signature(self.secret, b"{}", "not-a-timestamp", "v1=" + "0" * 64, now=self.now)

    def test_a_missing_timestamp_is_stale(self) -> None:
        with pytest.raises(StaleSignatureError):
            verify_signature(self.secret, b"{}", None, "v1=" + "0" * 64, now=self.now)


class TestTwentyWebhookConfig:
    def test_it_is_disabled_by_default(self) -> None:
        assert TwentyWebhookConfig.from_env({}).enabled is False

    @pytest.mark.parametrize("value", ["false", "0", "no", "", "off"])
    def test_falsey_values_leave_it_disabled(self, value: str) -> None:
        assert TwentyWebhookConfig.from_env({TWENTY_WEBHOOK_ENABLED_ENV: value}).enabled is False

    @pytest.mark.parametrize("value", ["true", "1", "TRUE", "yes", "on"])
    def test_truthy_values_enable_it(self, value: str) -> None:
        env = {TWENTY_WEBHOOK_ENABLED_ENV: value, TWENTY_WEBHOOK_SECRET_ENV: "a" * 32}
        assert TwentyWebhookConfig.from_env(env).enabled is True

    def test_enabling_it_without_a_secret_refuses_to_boot(self) -> None:
        with pytest.raises(TwentyWebhookSecretMissingError):
            TwentyWebhookConfig.from_env({TWENTY_WEBHOOK_ENABLED_ENV: "true"})

    def test_a_secret_alone_does_not_enable_it(self) -> None:
        assert TwentyWebhookConfig.from_env({TWENTY_WEBHOOK_SECRET_ENV: "a" * 32}).enabled is False


class TestTwentyWebhookRotation:
    """D15's quarterly rotation: add the incoming secret, re-point Twenty, remove the retired one.

    Both secrets are generated per test, like every other credential value in this file.
    """

    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)

    @staticmethod
    def _enabled(current: str | None, incoming: str | None = None) -> TwentyWebhookConfig:
        env = {TWENTY_WEBHOOK_ENABLED_ENV: "true"}
        if current is not None:
            env[TWENTY_WEBHOOK_SECRET_ENV] = current
        if incoming is not None:
            env[TWENTY_WEBHOOK_SECRET_NEXT_ENV] = incoming
        return TwentyWebhookConfig.from_env(env)

    def _verify(self, config: TwentyWebhookConfig, signing_secret: str) -> None:
        body = b'{"card":"synthetic"}'
        timestamp = str(int(self.now.timestamp()))
        config.verify(body, timestamp, sign(signing_secret, timestamp, body), now=self.now)

    def test_no_second_secret_by_default(self) -> None:
        assert TwentyWebhookConfig.from_env({TWENTY_WEBHOOK_SECRET_ENV: "a" * 32}).secret_next is None

    def test_both_secrets_verify_during_rotation(self) -> None:
        """Spec: "A request signed with the incoming secret verifies during rotation"."""
        current, incoming = _token(), _token()
        config = self._enabled(current, incoming)
        self._verify(config, current)
        self._verify(config, incoming)

    def test_a_third_secret_verifies_under_neither(self) -> None:
        config = self._enabled(_token(), _token())
        with pytest.raises(InvalidSignatureError):
            self._verify(config, _token())

    def test_a_retired_secret_stops_verifying_once_removed(self) -> None:
        """Spec: "A retired secret stops verifying once removed"."""
        retired, promoted = _token(), _token()
        during_rotation = self._enabled(retired, promoted)
        self._verify(during_rotation, retired)

        # Rotation completes: the incoming value is promoted into the current variable and the
        # retired value is deleted from the environment.
        after_rotation = self._enabled(promoted)
        self._verify(after_rotation, promoted)
        with pytest.raises(InvalidSignatureError):
            self._verify(after_rotation, retired)

    def test_only_the_incoming_secret_configured_still_verifies(self) -> None:
        """Mid-procedure, before promotion, the current variable may already be gone."""
        incoming = _token()
        self._verify(self._enabled(None, incoming), incoming)

    def test_freshness_is_still_checked_before_the_hmac(self) -> None:
        current = _token()
        config = self._enabled(current, _token())
        stale = self.now - timedelta(minutes=10)
        timestamp = str(int(stale.timestamp()))
        with pytest.raises(StaleSignatureError):
            config.verify(b"{}", timestamp, sign(current, timestamp, b"{}"), now=self.now)

    def test_a_missing_signature_is_rejected_with_two_secrets_set(self) -> None:
        config = self._enabled(_token(), _token())
        with pytest.raises(InvalidSignatureError):
            config.verify(b"{}", str(int(self.now.timestamp())), None, now=self.now)

    def test_enabled_with_neither_secret_refuses_to_boot(self) -> None:
        with pytest.raises(TwentyWebhookSecretMissingError):
            self._enabled(None, None)

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    @pytest.mark.parametrize("variable", [TWENTY_WEBHOOK_SECRET_ENV, TWENTY_WEBHOOK_SECRET_NEXT_ENV])
    def test_a_blank_secret_refuses_to_boot(self, variable: str, blank: str) -> None:
        """A blank variable is a provisioning mistake, not "no secret": say so at boot.

        Falling back to the other secret would let half a rotation run on a value nobody set.
        """
        env = {TWENTY_WEBHOOK_ENABLED_ENV: "true", TWENTY_WEBHOOK_SECRET_ENV: _token(), variable: blank}
        with pytest.raises(TwentyWebhookBlankSecretError) as raised:
            TwentyWebhookConfig.from_env(env)
        assert variable in str(raised.value)

    def test_a_blank_secret_is_refused_even_while_disabled(self) -> None:
        with pytest.raises(TwentyWebhookBlankSecretError):
            TwentyWebhookConfig.from_env({TWENTY_WEBHOOK_SECRET_ENV: ""})

    def test_the_invariant_holds_however_the_config_is_built(self) -> None:
        """Constructed directly, not just via `from_env` — the route trusts this, so it is checked."""
        with pytest.raises(TwentyWebhookSecretMissingError):
            TwentyWebhookConfig(enabled=True)
        with pytest.raises(TwentyWebhookBlankSecretError):
            TwentyWebhookConfig(enabled=True, secret=_token(), secret_next="")

    def test_a_disabled_config_verifies_nothing(self) -> None:
        """Fail closed: no configured secret means no signature is acceptable."""
        with pytest.raises(InvalidSignatureError):
            self._verify(TwentyWebhookConfig(), _token())

    def test_no_secret_value_reaches_the_error_messages(self) -> None:
        secret = _token()
        with pytest.raises(TwentyWebhookBlankSecretError) as raised:
            TwentyWebhookConfig(enabled=True, secret=secret, secret_next="   ")  # noqa: S106 — blank, not a secret
        assert secret not in str(raised.value)
