"""`--disable-socket` proven live: any socket attempt fails (task 1.4).

`conftest.py`'s `pytest_runtest_setup` hook calls `disable_socket()` for every test this package
collects, whether or not `--disable-socket` was passed on the command line — same pattern as
verdict-relay's `test_sockets_are_blocked` (`test_verdict_relay_package.py`). This test is the
proof: opening a raw socket from inside a collected test raises `SocketBlockedError`.
"""

from __future__ import annotations

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_opening_a_socket_raises_socket_blocked_error() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket()


def test_a_connect_attempt_is_also_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("127.0.0.1", 1), timeout=1)
