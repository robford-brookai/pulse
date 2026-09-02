"""`billing_connector.config` — task 1.2, spec "One credential, names in config, values from the
environment".

Every required environment variable is faked as a plain `dict`; `conftest.py` (task 1.4) blocks
sockets for the whole suite — this module makes no network call regardless.
"""

from __future__ import annotations

import re

import pytest
from billing_connector.config import (
    LEDGER_BASE_URL_ENV_VAR,
    QUEUE_URL_ENV_VAR,
    STALE_AFTER_ENV_VAR,
    TOKEN_ENV_VAR,
    Config,
    MissingConfigVariableError,
    RegistryUnavailableError,
)

#: A complete, synthetic environment — no real credential value, per the repo's no-secret fixture
#: posture (mirrors `verdict_relay.production`'s `COMPLETE_ENV`).
COMPLETE_ENV: dict[str, str] = {
    TOKEN_ENV_VAR: "fixture-token-do-not-use",
    QUEUE_URL_ENV_VAR: "https://queue.test/billing-connector",
    LEDGER_BASE_URL_ENV_VAR: "https://ledger.test",
}

#: The variables `from_env()` requires present — `STALE_AFTER_ENV_VAR` has a default and is
#: deliberately excluded from this set.
_REQUIRED_ENV_VARS = (TOKEN_ENV_VAR, QUEUE_URL_ENV_VAR, LEDGER_BASE_URL_ENV_VAR)


class TestFromEnvRoundTrip:
    """Scenario: a complete environment resolves; each missing variable names itself."""

    def test_a_complete_environment_resolves(self) -> None:
        config = Config.from_env(COMPLETE_ENV)

        assert config.credential_name == TOKEN_ENV_VAR
        assert config.queue_url == COMPLETE_ENV[QUEUE_URL_ENV_VAR]
        assert config.ledger_base_url == COMPLETE_ENV[LEDGER_BASE_URL_ENV_VAR]

    def test_stale_after_defaults_when_unset(self) -> None:
        config = Config.from_env(COMPLETE_ENV)

        assert config.stale_after.total_seconds() == 24 * 60 * 60

    def test_stale_after_reads_a_configured_duration(self) -> None:
        env = {**COMPLETE_ENV, STALE_AFTER_ENV_VAR: "3600"}

        config = Config.from_env(env)

        assert config.stale_after.total_seconds() == 3600

    @pytest.mark.parametrize("missing_var", _REQUIRED_ENV_VARS)
    def test_each_missing_variable_names_itself(self, missing_var: str) -> None:
        env = {name: value for name, value in COMPLETE_ENV.items() if name != missing_var}

        with pytest.raises(MissingConfigVariableError) as exc_info:
            Config.from_env(env)

        assert exc_info.value.name == missing_var
        assert missing_var in str(exc_info.value)

    def test_no_configured_value_reaches_the_missing_variable_error(self) -> None:
        env = {name: value for name, value in COMPLETE_ENV.items() if name != QUEUE_URL_ENV_VAR}

        with pytest.raises(MissingConfigVariableError) as exc_info:
            Config.from_env(env)

        message = str(exc_info.value)
        for name, value in COMPLETE_ENV.items():
            if name != QUEUE_URL_ENV_VAR:
                assert value not in message

    def test_from_env_defaults_to_the_real_process_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, value in COMPLETE_ENV.items():
            monkeypatch.setenv(name, value)

        config = Config.from_env()

        assert config.queue_url == COMPLETE_ENV[QUEUE_URL_ENV_VAR]


class TestNoCredentialValueIsEverHeld:
    """Scenario: the credential's value is never reachable from this module's own surface —
    `credential_name` holds the environment variable's *name*, not what it is set to."""

    def test_credential_name_is_the_env_var_name_not_its_value(self) -> None:
        config = Config.from_env(COMPLETE_ENV)

        assert config.credential_name == TOKEN_ENV_VAR
        assert config.credential_name != COMPLETE_ENV[TOKEN_ENV_VAR]

    def test_no_configured_value_is_reachable_from_repr_or_str(self) -> None:
        config = Config.from_env(COMPLETE_ENV)

        # queue_url and ledger_base_url are plain configuration, not secrets — only the token's
        # value (never held by any field) is barred from ever appearing.
        for text in (repr(config), str(config)):
            assert COMPLETE_ENV[TOKEN_ENV_VAR] not in text

    def test_config_has_no_field_shaped_to_hold_a_secret_value(self) -> None:
        """Belt-and-suspenders: no field name on `Config` looks like it holds a resolved secret
        (only `credential_name` — a name — is credential-shaped)."""
        secret_shaped = re.compile(r"(token|credential_value|secret|password)", re.IGNORECASE)
        for field_name in Config.__dataclass_fields__:
            if field_name == "credential_name":
                continue
            assert not secret_shaped.search(field_name), f"{field_name} looks like it might hold a secret value"


class TestVerdictTypesDefersToTheRegistry:
    """`verdict_types()` is not populated by `from_env()` — task 1.3 owns `billing.rules.registry`;
    until it lands, the gap is explicit rather than a silent empty set."""

    def test_verdict_types_raises_naming_task_1_3_while_the_registry_is_absent(self) -> None:
        config = Config.from_env(COMPLETE_ENV)

        with pytest.raises(RegistryUnavailableError) as exc_info:
            config.verdict_types()

        assert "1.3" in str(exc_info.value)

    def test_from_env_never_imports_the_registry(self) -> None:
        """Constructing a `Config` must not require `billing.rules.registry` to exist — only
        calling `verdict_types()` does."""
        # If from_env() touched the registry this would already have raised above; asserting a
        # plain construction succeeds is the whole test.
        assert Config.from_env(COMPLETE_ENV) is not None
