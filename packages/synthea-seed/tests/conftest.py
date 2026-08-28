"""Socket-blocked test posture: no live network in any synthea-seed test.

Generation never runs in tests and the JAR fetcher is exercised only through injected fakes;
this hook makes that structural. Blocks sockets for every run that collects this package,
including the combined `task test` run — same pattern as consent-ingress, verdict-relay, and
schedules.
"""

from __future__ import annotations

from pytest_socket import disable_socket


def pytest_runtest_setup() -> None:
    disable_socket()
