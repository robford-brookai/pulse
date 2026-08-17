"""Read-back verification tests (pulse-app-scaffold 4.1) — every claim on a fake transport.

No test here reaches a Twenty instance: sockets are disabled module-wide and the transport is
scripted. The live run this module exists for (`python -m pulse_core.twenty_verify --target dev`)
drives the same code over `MetadataApiTransport`; these tests pin what that run asserts —
spec: "Read-back matches the artifact".
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pulse_core import twenty_deploy as td
from pulse_core import twenty_verify as tv
from pulse_core.twenty_metadata import ARTIFACT_PATH
from pytest_socket import disable_socket, enable_socket

#: A value that would be workspace data on a live instance — present only inside fake remote
#: state, so a receipt echoing remote payloads is a test failure. Synthetic.
SYNTHETIC_RECORD_VALUE = "Wilhelmina Testpatient (MRN SYNTH-000123)"

FAKE_CRED = "t-dev"


@pytest.fixture(autouse=True)
def _no_sockets() -> Iterator[None]:
    disable_socket()
    yield
    enable_socket()


@pytest.fixture(scope="module")
def artifact() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(ARTIFACT_PATH.read_text())
    return loaded


@pytest.fixture
def env() -> dict[str, str]:
    return {"PULSE_TWENTY_DEV_URL": "https://dev.invalid", "PULSE_TWENTY_DEV_TOKEN": FAKE_CRED}


class _FakeTransport:
    """A scripted target: a fixed remote state and a recorder for anything sent."""

    def __init__(self, state: dict[str, td.RemoteRecord] | None = None) -> None:
        self.state = state or {}
        self.sent: list[tuple[str, str]] = []
        self.reads = 0

    def read_state(self) -> dict[str, td.RemoteRecord]:
        self.reads += 1
        return dict(self.state)

    def send(self, verb: td.Verb, item: td.PlanItem) -> None:
        self.sent.append((verb, item.name))


def _matching_state(artifact: dict[str, Any]) -> dict[str, td.RemoteRecord]:
    """The state a target is in after this exact artifact has been applied to it."""
    return {
        td.operation_key(operation): td.RemoteRecord(record_id=f"rec-{index}", payload=td.desired_payload(operation))
        for index, operation in enumerate(artifact["operations"])
    }


# --- Read-back matches --------------------------------------------------------------------------


def test_a_matching_target_verifies_clean(artifact: dict[str, Any]) -> None:
    """Spec: "Read-back matches the artifact" — every operation present, re-apply all no-ops."""
    transport = _FakeTransport(state=_matching_state(artifact))

    receipt = tv.verify(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert receipt.ok
    assert receipt.counts["present"] == len(artifact["operations"])
    assert receipt.missing == ()
    assert receipt.reapply == {"create": 0, "update": 0, "noop": len(artifact["operations"])}
    assert transport.sent == []


def test_a_missing_operation_fails_verification_by_name(artifact: dict[str, Any]) -> None:
    """A key the read-back lacks is named in the receipt, and nothing is sent to repair it."""
    state = _matching_state(artifact)
    absent = artifact["operations"][0]
    del state[td.operation_key(absent)]
    transport = _FakeTransport(state=state)

    receipt = tv.verify(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert not receipt.ok
    assert receipt.missing == (td.operation_name(absent),)
    assert receipt.reapply is None
    assert transport.sent == []


def test_a_drifted_target_fails_the_all_noop_assertion(artifact: dict[str, Any]) -> None:
    """Present-but-drifted passes read-back and fails re-apply: the receipt shows the update."""
    state = _matching_state(artifact)
    key = td.operation_key(artifact["operations"][0])
    drifted = dict(state[key].payload) | {"labelSingular": "Edited In The UI"}
    transport = _FakeTransport(state=state | {key: td.RemoteRecord(record_id=state[key].record_id, payload=drifted)})

    receipt = tv.verify(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert not receipt.ok
    assert receipt.missing == ()
    assert receipt.reapply is not None
    assert receipt.reapply["update"] == 1


def test_an_invalid_artifact_is_refused_before_any_read(tmp_path: Path) -> None:
    broken = tmp_path / "operations.json"
    broken.write_text(json.dumps({"artifactVersion": "1", "operations": [{"operation": "createUniverse"}]}))
    transport = _FakeTransport()

    with pytest.raises(td.DeployError):
        tv.verify(target="dev", artifact_path=broken, transport=transport)
    assert transport.reads == 0


# --- Receipt containment ------------------------------------------------------------------------


def test_the_receipt_carries_names_counts_and_the_checksum_only(artifact: dict[str, Any], env: dict[str, str]) -> None:
    """Names, counts, checksum — no remote payloads, no credential (spec: receipts are safe)."""
    state = _matching_state(artifact)
    key = td.operation_key(artifact["operations"][0])
    poisoned = dict(state[key].payload) | {"labelSingular": SYNTHETIC_RECORD_VALUE}
    transport = _FakeTransport(state=state | {key: td.RemoteRecord(record_id="rec-0", payload=poisoned)})

    receipt = tv.verify(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)
    body = json.dumps(receipt.to_dict())

    assert set(receipt.to_dict()) == {
        "target",
        "artifact",
        "checksum",
        "ok",
        "counts",
        "missing",
        "reapply",
        "failure",
        "optionValueEncoding",
    }
    # 4.2 reads raw tokens back from the live schema — the receipt says how they were encoded.
    assert "UPPER_SNAKE_CASE" in receipt.to_dict()["optionValueEncoding"]
    assert SYNTHETIC_RECORD_VALUE not in body
    assert env["PULSE_TWENTY_DEV_TOKEN"] not in body
    assert receipt.checksum == td.artifact_checksum(ARTIFACT_PATH)


# --- CLI ----------------------------------------------------------------------------------------


def test_main_prints_the_receipt_and_exits_zero_on_a_match(
    artifact: dict[str, Any], env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The script's output IS the verification receipt (work order 4.1)."""
    transport = _FakeTransport(state=_matching_state(artifact))

    exit_code = tv.main(["--target", "dev"], env=env, transport=transport)

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] is True
    assert printed["target"] == "dev"
    assert printed["counts"]["present"] == len(artifact["operations"])


def test_main_exits_nonzero_on_any_readback_mismatch(
    artifact: dict[str, Any], env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    state = _matching_state(artifact)
    del state[td.operation_key(artifact["operations"][0])]

    exit_code = tv.main(["--target", "dev"], env=env, transport=_FakeTransport(state=state))

    assert exit_code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] is False
    assert printed["missing"] == [td.operation_name(artifact["operations"][0])]


def test_main_without_credentials_names_the_variables_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verification is live-only: no credentials is an error, never an empty-state pass."""
    exit_code = tv.main(["--target", "dev"], env={})

    printed = capsys.readouterr().out
    assert exit_code == 1
    assert "PULSE_TWENTY_DEV_URL" in printed
    assert "PULSE_TWENTY_DEV_TOKEN" in printed
