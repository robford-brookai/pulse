"""twenty_projection is importable as an installed workspace member, not by path accident,
its suite runs socket-blocked, and the consumer entrypoint fails by name when unconfigured."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import twenty_projection
from pytest_socket import SocketBlockedError
from twenty_projection import consumer


def test_package_imports_from_its_src_tree() -> None:
    assert twenty_projection.__file__ is not None
    pkg_path = Path(twenty_projection.__file__).resolve()
    assert pkg_path.parent.name == "twenty_projection"
    assert (pkg_path.parent / "py.typed").is_file()


def test_sockets_are_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket()


def test_unconfigured_consumer_fails_by_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`task projection:consume` must fail with a named message, never an ImportError.

    The full startup contract (every missing variable named) is pinned in test_consumer.py;
    this keeps the entrypoint posture the stub established: exit 2, a message, no traceback.
    """
    for name in ("PULSE_TWENTY_DEV_URL", "PULSE_TWENTY_DEV_TOKEN", "SQS_QUEUE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert consumer.main(["--target", "dev"]) == 2
    captured = capsys.readouterr()
    assert "startup failed" in captured.err
