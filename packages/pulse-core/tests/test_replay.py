"""The replay facility's environment surface: named once, failing by name.

`pulse_core.replay` exists so a connector that repaints itself from the journal does not have to
hold a second credential name of its own (connector-kit spec: "one connector, one credential" —
`test_connector_credential_gate.py` enforces the ceiling). These tests pin the two things that
makes true: the variables are the kit's, and a missing one fails startup naming every absent
variable and no value.
"""

from __future__ import annotations

import httpx
import pytest
from pulse_core.replay import (
    REPLAY_BASE_URL_ENV_VAR,
    REPLAY_TOKEN_ENV_VAR,
    ReplayStartupError,
    replay_client_from_env,
)

WRITER_ID = "twenty-projection"
COMPLETE_ENV = {
    REPLAY_BASE_URL_ENV_VAR: "https://ledger.fixture",
    REPLAY_TOKEN_ENV_VAR: "fixture-replay-token",
}


def _transport(events: list[dict[str, object]]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {COMPLETE_ENV[REPLAY_TOKEN_ENV_VAR]}"
        return httpx.Response(200, json={"events": events})

    return httpx.MockTransport(handle)


def test_the_replay_client_reads_a_subject_history_under_the_environments_credential() -> None:
    events: list[dict[str, object]] = [{"event_id": "evt-1", "seq": 1}]
    with replay_client_from_env(COMPLETE_ENV, writer_id=WRITER_ID, transport=_transport(events)) as client:
        assert client.subject_history("enrollment", "pt-0001") == events


@pytest.mark.parametrize("dropped", [REPLAY_BASE_URL_ENV_VAR, REPLAY_TOKEN_ENV_VAR])
def test_a_missing_variable_fails_startup_by_name(dropped: str) -> None:
    env = {name: value for name, value in COMPLETE_ENV.items() if name != dropped}
    with pytest.raises(ReplayStartupError) as raised:
        replay_client_from_env(env, writer_id=WRITER_ID)
    assert raised.value.missing == (dropped,)
    assert dropped in str(raised.value)


def test_an_empty_value_counts_as_missing() -> None:
    """An unset secret reaches a job as an empty string; treating it as present would read an
    empty history, the one answer a rebuild must never confuse with "this subject has none"."""
    with pytest.raises(ReplayStartupError) as raised:
        replay_client_from_env({**COMPLETE_ENV, REPLAY_TOKEN_ENV_VAR: ""}, writer_id=WRITER_ID)
    assert raised.value.missing == (REPLAY_TOKEN_ENV_VAR,)


def test_the_startup_failure_never_carries_a_value() -> None:
    secret = "fixture-replay-token"  # noqa: S105 — a fixture placeholder, not a credential
    with pytest.raises(ReplayStartupError) as raised:
        replay_client_from_env({REPLAY_TOKEN_ENV_VAR: secret}, writer_id=WRITER_ID)
    assert secret not in str(raised.value)
