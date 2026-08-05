"""Socket-blocked test posture: no live network in any verdict-relay test.

The `--disable-socket` flag only guards invocations that remember to pass it; this
hook blocks sockets for every run that collects this package, including the combined
`task test` run from the repo root.
"""

from __future__ import annotations

from pytest_socket import disable_socket


def pytest_runtest_setup() -> None:
    disable_socket()
