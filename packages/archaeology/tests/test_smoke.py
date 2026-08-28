"""Smoke-CLI tests: names-only output, exit status as the access receipt.

Socket-blocked (conftest.py); the client factory is faked at the boundary.
"""

from __future__ import annotations

from typing import Any

import pytest
from archaeology.client import ENV_HOST, ENV_PASSWORD_REF, ENV_USER, ArchaeologyConfig, MissingEnvVarsError
from archaeology.smoke import main

_SYNTHETIC_VALUE = "not-a-real-secret"
_MUST_NOT_BE_CALLED = "factory must not be called"


class FakeDatabase:
    def __init__(self, collections: list[str]) -> None:
        self._collections = collections

    def list_collection_names(self) -> list[str]:
        return list(self._collections)


class FakeClient:
    def __init__(self, collections: dict[str, list[str]]) -> None:
        self._collections = collections
        self.closed = False

    def __getitem__(self, name: str) -> FakeDatabase:
        return FakeDatabase(self._collections[name])

    def close(self) -> None:
        self.closed = True


def _env() -> dict[str, str]:
    return {
        ENV_HOST: "legacy-cluster.example.internal",
        ENV_USER: "archaeology_ro",
        ENV_PASSWORD_REF: "env:SYNTHETIC_SECRET",
        "SYNTHETIC_SECRET": _SYNTHETIC_VALUE,
        "ARCHAEOLOGY_MONGO_DB": "prod",
    }


def test_happy_path_prints_sorted_names_only_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeClient({"prod": ["users", "alerts", "readings"]})

    def factory(config: ArchaeologyConfig, **_: Any) -> FakeClient:
        assert config.database == "prod"
        return fake

    status = main(["--list-collections"], client_factory=factory, environ=_env())
    assert status == 0
    out = capsys.readouterr().out
    assert out == "alerts\nreadings\nusers\n"
    assert fake.closed


def test_missing_env_is_a_nonzero_receipt_naming_names(capsys: pytest.CaptureFixture[str]) -> None:
    def factory(*_: Any, **__: Any) -> FakeClient:  # pragma: no cover — never reached
        raise AssertionError(_MUST_NOT_BE_CALLED)

    status = main(["--list-collections"], client_factory=factory, environ={})
    assert status == 1
    err = capsys.readouterr().err
    assert ENV_HOST in err and ENV_USER in err and ENV_PASSWORD_REF in err


def test_factory_refusal_is_a_nonzero_receipt(capsys: pytest.CaptureFixture[str]) -> None:
    def factory(*_: Any, **__: Any) -> FakeClient:
        raise MissingEnvVarsError((ENV_HOST,))

    status = main(["--list-collections"], client_factory=factory, environ=_env())
    assert status == 1
    assert "smoke:" in capsys.readouterr().err


def test_no_flag_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([], environ=_env())
    assert excinfo.value.code == 2
