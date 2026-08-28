"""verdict_relay is importable as an installed workspace member, not by path accident,
and its suite runs socket-blocked."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import verdict_relay
from pytest_socket import SocketBlockedError


def test_package_imports_from_its_src_tree():
    assert verdict_relay.__file__ is not None
    pkg_path = Path(verdict_relay.__file__).resolve()
    assert pkg_path.parent.name == "verdict_relay"
    assert (pkg_path.parent / "py.typed").is_file()


def test_sockets_are_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket()
