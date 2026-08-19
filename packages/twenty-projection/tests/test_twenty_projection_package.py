"""twenty_projection is importable as an installed workspace member, not by path accident,
its suite runs socket-blocked, and the consumer stub fails by name until task 2.3."""

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


def test_consumer_stub_fails_by_name(capsys: pytest.CaptureFixture[str]) -> None:
    """`task projection:consume` must fail with a named message, never an ImportError."""
    assert consumer.main() == 2
    captured = capsys.readouterr()
    assert "not implemented" in captured.err
    assert "task 2.3" in captured.err
