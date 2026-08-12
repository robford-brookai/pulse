"""Client-factory tests: fail-fast env contract, secret-ref resolution, write-role refusal.

Everything runs socket-blocked (conftest.py); the Mongo driver is faked at the
construction boundary via `client_cls`. All credentials here are synthetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from archaeology.client import (
    ENV_HOST,
    ENV_PASSWORD_REF,
    ENV_TLS,
    ENV_USER,
    REQUIRED_ENV_VARS,
    ArchaeologyConfig,
    InvalidEnvValueError,
    MissingEnvVarsError,
    SecretRefError,
    WriteRoleRefusedError,
    create_readonly_client,
)
from pymongo.errors import OperationFailure

# --- Fakes at the driver boundary -------------------------------------------

_DENIED = "not authorized on admin to execute command"
_SYNTHETIC_VALUE = "not-a-real-secret"


class FakeAdmin:
    def __init__(self, roles: list[dict[str, str]] | None, fail: bool = False) -> None:
        self._roles = roles or []
        self._fail = fail

    def command(self, name: str) -> dict[str, Any]:
        assert name == "connectionStatus"
        if self._fail:
            raise OperationFailure(_DENIED)
        return {"authInfo": {"authenticatedUserRoles": self._roles}}


class FakeMongoClient:
    """Captures constructor kwargs; answers connectionStatus with fixture roles."""

    def __init__(self, roles: list[dict[str, str]] | None = None, fail_detection: bool = False) -> None:
        self.roles = roles
        self.fail_detection = fail_detection
        self.kwargs: dict[str, Any] = {}
        self.closed = False
        self.admin = FakeAdmin(self.roles, self.fail_detection)

    def __call__(self, **kwargs: Any) -> FakeMongoClient:
        # Used as `client_cls`: constructing returns self, with kwargs captured.
        self.kwargs = kwargs
        return self

    def close(self) -> None:
        self.closed = True


def _env(**overrides: str) -> dict[str, str]:
    base = {
        ENV_HOST: "legacy-cluster.example.internal",
        ENV_USER: "archaeology_ro",
        ENV_PASSWORD_REF: "env:SYNTHETIC_SECRET",
        "SYNTHETIC_SECRET": _SYNTHETIC_VALUE,
    }
    base.update(overrides)
    return base


# --- Fail-fast env contract ---------------------------------------------------


def test_missing_all_env_vars_fails_fast_naming_every_name() -> None:
    with pytest.raises(MissingEnvVarsError) as excinfo:
        ArchaeologyConfig.from_env({})
    message = str(excinfo.value)
    for name in REQUIRED_ENV_VARS:
        assert name in message
    assert excinfo.value.missing == REQUIRED_ENV_VARS


def test_partially_missing_env_names_only_the_missing_ones() -> None:
    env = {ENV_HOST: "legacy-cluster.example.internal"}
    with pytest.raises(MissingEnvVarsError) as excinfo:
        ArchaeologyConfig.from_env(env)
    assert excinfo.value.missing == (ENV_USER, ENV_PASSWORD_REF)
    assert ENV_HOST not in str(excinfo.value)


def test_missing_env_raises_before_any_client_construction() -> None:
    """The factory fails before the driver boundary is ever reached."""
    fake = FakeMongoClient()
    with pytest.raises(MissingEnvVarsError):
        create_readonly_client(client_cls=fake, environ={})
    assert fake.kwargs == {}


def test_error_messages_carry_names_never_values() -> None:
    env = {ENV_HOST: "legacy-cluster.example.internal", ENV_USER: ""}
    with pytest.raises(MissingEnvVarsError) as excinfo:
        ArchaeologyConfig.from_env(env)
    assert "legacy-cluster.example.internal" not in str(excinfo.value)


def test_invalid_tls_toggle_is_rejected_by_name() -> None:
    with pytest.raises(InvalidEnvValueError) as excinfo:
        ArchaeologyConfig.from_env(_env(**{ENV_TLS: "maybe"}))
    assert ENV_TLS in str(excinfo.value)


# --- Secret-ref resolution ----------------------------------------------------


def test_env_ref_resolves_and_reaches_the_driver_boundary() -> None:
    fake = FakeMongoClient(roles=[{"role": "read", "db": "prod"}])
    client = create_readonly_client(client_cls=fake, environ=_env())
    assert client.kwargs["password"] == _SYNTHETIC_VALUE
    assert client.kwargs["username"] == "archaeology_ro"


def test_env_ref_to_unset_var_names_the_ref_not_a_value() -> None:
    env = _env(**{ENV_PASSWORD_REF: "env:UNSET_SYNTHETIC"})
    with pytest.raises(SecretRefError) as excinfo:
        create_readonly_client(client_cls=FakeMongoClient(), environ=env)
    assert "UNSET_SYNTHETIC" in str(excinfo.value)


def test_file_ref_resolves(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("not-a-real-secret\n")
    env = _env(**{ENV_PASSWORD_REF: f"file:{secret_file}"})
    fake = FakeMongoClient(roles=[])
    client = create_readonly_client(client_cls=fake, environ=env)
    assert client.kwargs["password"] == _SYNTHETIC_VALUE


def test_file_ref_to_missing_file_is_refused() -> None:
    env = _env(**{ENV_PASSWORD_REF: "file:/nonexistent/synthetic-secret"})
    with pytest.raises(SecretRefError):
        create_readonly_client(client_cls=FakeMongoClient(), environ=env)


def test_literal_credential_as_ref_is_refused() -> None:
    """A bare value in the ref slot is never accepted as a password."""
    env = _env(**{ENV_PASSWORD_REF: "not-a-real-secret"})
    with pytest.raises(SecretRefError) as excinfo:
        create_readonly_client(client_cls=FakeMongoClient(), environ=env)
    assert "not-a-real-secret" not in str(excinfo.value)


# --- Read-only enforcement ----------------------------------------------------


def test_write_role_user_is_refused_naming_the_role() -> None:
    fake = FakeMongoClient(roles=[{"role": "readWrite", "db": "prod"}])
    with pytest.raises(WriteRoleRefusedError) as excinfo:
        create_readonly_client(client_cls=fake, environ=_env())
    assert "readWrite" in str(excinfo.value)
    assert excinfo.value.roles == ("readWrite",)


def test_refused_client_is_closed_and_not_returned() -> None:
    fake = FakeMongoClient(roles=[{"role": "atlasAdmin", "db": "admin"}])
    with pytest.raises(WriteRoleRefusedError):
        create_readonly_client(client_cls=fake, environ=_env())
    assert fake.closed


def test_read_only_roles_construct_successfully() -> None:
    fake = FakeMongoClient(roles=[{"role": "read", "db": "prod"}, {"role": "readAnyDatabase", "db": "admin"}])
    client = create_readonly_client(client_cls=fake, environ=_env())
    assert client is fake
    assert not fake.closed


def test_undetectable_roles_proceed_the_atlas_role_is_the_control() -> None:
    """connectionStatus refused -> construction proceeds (design decision 3)."""
    fake = FakeMongoClient(fail_detection=True)
    client = create_readonly_client(client_cls=fake, environ=_env())
    assert client is fake


# --- Streamline-inherited connection posture -----------------------------------


def test_streamline_timeout_and_tls_posture_reaches_the_driver() -> None:
    """Bounded waits (mongo-stream defaults) and TLS-on-by-default, retryWrites off."""
    fake = FakeMongoClient(roles=[])
    client = create_readonly_client(client_cls=fake, environ=_env())
    assert client.kwargs["serverSelectionTimeoutMS"] == 30_000
    assert client.kwargs["connectTimeoutMS"] == 20_000
    assert client.kwargs["socketTimeoutMS"] == 600_000
    assert client.kwargs["tls"] is True
    assert client.kwargs["retryWrites"] is False


def test_timeouts_and_tls_are_env_tunable() -> None:
    env = _env(
        ARCHAEOLOGY_MONGO_TLS="false",
        ARCHAEOLOGY_MONGO_SERVER_SELECTION_TIMEOUT_MS="5000",
        ARCHAEOLOGY_MONGO_CONNECT_TIMEOUT_MS="4000",
        ARCHAEOLOGY_MONGO_SOCKET_TIMEOUT_MS="60000",
    )
    fake = FakeMongoClient(roles=[])
    client = create_readonly_client(client_cls=fake, environ=env)
    assert client.kwargs["serverSelectionTimeoutMS"] == 5000
    assert client.kwargs["connectTimeoutMS"] == 4000
    assert client.kwargs["socketTimeoutMS"] == 60_000
    assert client.kwargs["tls"] is False
