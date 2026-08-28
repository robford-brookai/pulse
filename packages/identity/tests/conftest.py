"""Socket-blocked test posture: no live network in any identity test.

The `--disable-socket` flag only guards invocations that remember to pass it; this
hook blocks sockets for every run that collects this package, including the combined
`task test` run from the repo root. Same pattern as verdict-relay and schedules.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pytest_socket import disable_socket

# The root `task test` run collects every package's tests with `--import-mode=importlib`,
# which does not add a test module's directory to sys.path (unlike the default "prepend"
# mode). `tests/fixtures/` is a real package (has __init__.py) meant to be imported as
# `fixtures.loader` from any test module here and from later waves' test files
# (3.1's matcher tests, 5.1's determinism test) — put this directory on sys.path once, here,
# so that import resolves under either import mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def pytest_runtest_setup() -> None:
    disable_socket()
