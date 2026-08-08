"""consent-ingress is importable as an installed workspace member, not by path accident,
and its suite runs socket-blocked. Wave 0 scaffold only — row_source, declarer, and cli
land in waves 1-2 (tasks 2.x-4.1)."""

from __future__ import annotations

import socket
from pathlib import Path

import consent_ingress
import pytest
from pytest_socket import SocketBlockedError


def test_package_imports_from_its_src_tree():
    assert consent_ingress.__file__ is not None
    pkg_path = Path(consent_ingress.__file__).resolve()
    assert pkg_path.parent.name == "consent_ingress"
    assert (pkg_path.parent / "py.typed").is_file()


def test_sockets_are_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket()
