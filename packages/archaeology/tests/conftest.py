"""Socket-blocked test posture: no live network in any archaeology test.

The `--disable-socket` flag only guards invocations that remember to pass it; this
hook blocks sockets for every run that collects this package, including the combined
`task test` run from the repo root. Same pattern as verdict-relay, schedules, and
consent-ingress. The Mongo driver is faked at the client-construction boundary —
no test ever builds a real `MongoClient`.
"""

from __future__ import annotations

from pytest_socket import disable_socket


def pytest_runtest_setup() -> None:
    disable_socket()
