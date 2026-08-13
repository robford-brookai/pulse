"""Deploy-step tests (pulse-app-scaffold 3.3) — every claim the spec makes, on a fake transport.

No test here reaches a Twenty instance: sockets are disabled module-wide, and the only two
transports the suite drives are a scripted in-memory fake (plan and idempotence claims) and the
real `MetadataApiTransport` over `httpx.MockTransport` (the response-body containment claim, which
is only meaningful against the code that actually reads a response).

The four scripted target states the work order names are the four `_FakeTransport` constructions
below: empty, matching, drifted, and one failing operation whose response body carries a synthetic
record value.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pulse_core import twenty_deploy as td
from pulse_core.twenty_metadata import ARTIFACT_PATH
from pytest_socket import disable_socket, enable_socket

#: A value that would be patient data on a live workspace. It exists only inside a fake response
#: body, so that a receipt or log line echoing the body is a test failure rather than a review
#: question. Synthetic — no real record has ever carried it.
SYNTHETIC_RECORD_VALUE = "Wilhelmina Testpatient (MRN SYNTH-000123)"

#: Fake credentials, named through constants so no literal sits at a `token=` argument.
FAKE_CRED = "t-dev"
FAKE_PROD_CRED = "t-prod"


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
    """A scripted target: a fixed remote state, a recorder, and an optional scripted failure."""

    def __init__(
        self,
        state: dict[str, td.RemoteRecord] | None = None,
        fail_on: str | None = None,
        fail_status: int = 422,
    ) -> None:
        self.state = state or {}
        self.fail_on = fail_on
        self.fail_status = fail_status
        self.sent: list[tuple[str, str]] = []
        self.reads = 0

    def read_state(self) -> dict[str, td.RemoteRecord]:
        self.reads += 1
        return dict(self.state)

    def send(self, verb: td.Verb, item: td.PlanItem) -> None:
        self.sent.append((verb, item.name))
        if self.fail_on is not None and item.name == self.fail_on:
            raise td.TransportError(self.fail_status)


def _matching_state(artifact: dict[str, Any]) -> dict[str, td.RemoteRecord]:
    """The state a target is in after this exact artifact has been applied to it."""
    return {
        td.operation_key(operation): td.RemoteRecord(record_id=f"rec-{index}", payload=td.desired_payload(operation))
        for index, operation in enumerate(artifact["operations"])
    }


def _drifted_state(artifact: dict[str, Any]) -> dict[str, td.RemoteRecord]:
    """The matching state with exactly one object's label edited server-side."""
    state = _matching_state(artifact)
    key = td.operation_key(artifact["operations"][0])
    drifted = dict(state[key].payload) | {"labelSingular": "Edited In The UI"}
    return state | {key: td.RemoteRecord(record_id=state[key].record_id, payload=drifted)}


# --- Validate before apply ---------------------------------------------------------------------


def test_invalid_artifact_is_refused_before_any_operation(tmp_path: Path) -> None:
    """Spec: "An invalid artifact is refused before any operation"."""
    broken = tmp_path / "operations.json"
    broken.write_text(json.dumps({"artifactVersion": "1", "operations": [{"operation": "createUniverse"}]}))
    transport = _FakeTransport()

    with pytest.raises(td.DeployError) as raised:
        td.deploy(target="dev", artifact_path=broken, transport=transport)

    assert "artifact schema" in str(raised.value)
    assert transport.sent == []
    assert transport.reads == 0


def test_unparseable_artifact_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "operations.json"
    broken.write_text("{not json")
    transport = _FakeTransport()

    with pytest.raises(td.DeployError):
        td.deploy(target="dev", artifact_path=broken, transport=transport)
    assert transport.sent == []


def test_the_committed_artifact_passes_validation() -> None:
    """The gate is only a gate if the artifact the tree ships clears it."""
    assert td.validation_findings(ARTIFACT_PATH) == ()


# --- Idempotence -------------------------------------------------------------------------------


def test_empty_target_creates_every_operation(artifact: dict[str, Any]) -> None:
    transport = _FakeTransport()

    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert receipt.counts["create"] == len(artifact["operations"])
    assert receipt.counts["update"] == 0
    assert [verb for verb, _ in transport.sent] == ["create"] * len(artifact["operations"])


def test_reapply_of_the_same_artifact_is_all_noops(artifact: dict[str, Any]) -> None:
    """Spec: "Re-apply of the same artifact is all no-ops"."""
    transport = _FakeTransport(state=_matching_state(artifact))

    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert receipt.counts["create"] == 0
    assert receipt.counts["update"] == 0
    assert receipt.counts["noop"] == len(artifact["operations"])
    assert transport.sent == []


def test_no_delete_is_ever_attempted(artifact: dict[str, Any]) -> None:
    """Not "we do not call delete" but "there is no verb to call": deletion is unrepresentable."""
    extra = _matching_state(artifact) | {
        "9f1d6b0e-0000-4000-8000-000000000000": td.RemoteRecord(
            record_id="rec-orphan", payload={"nameSingular": "orphanObject"}
        )
    }
    transport = _FakeTransport(state=extra)

    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert transport.sent == []
    assert set(receipt.counts) == {"create", "update", "noop"}
    assert td.VERBS == ("create", "update")


def test_drift_is_an_update_not_a_recreate(artifact: dict[str, Any]) -> None:
    transport = _FakeTransport(state=_drifted_state(artifact))

    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert receipt.counts["update"] == 1
    assert receipt.counts["create"] == 0
    assert [verb for verb, _ in transport.sent] == ["update"]


def test_a_role_is_keyed_on_its_name(artifact: dict[str, Any]) -> None:
    """Roles carry no `universalIdentifier` in the artifact; their identity key is their name."""
    role = next(operation for operation in artifact["operations"] if operation["operation"] == "createRole")
    assert td.operation_key(role) == f"role:{role['name']}"


# --- Promotion ---------------------------------------------------------------------------------


def test_two_targets_one_artifact_matching_checksums(artifact: dict[str, Any]) -> None:
    """Spec: "Two targets, one artifact, matching checksums"."""
    env = {
        "PULSE_TWENTY_DEV_URL": "https://dev.invalid",
        "PULSE_TWENTY_DEV_TOKEN": FAKE_CRED,
        "PULSE_TWENTY_PROD_URL": "https://prod.invalid",
        "PULSE_TWENTY_PROD_TOKEN": FAKE_PROD_CRED,
    }
    # The two targets differ only in where they resolve to — the artifact is one file.
    assert td.resolve_target("dev", env).url != td.resolve_target("prod", env).url

    dev = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=_FakeTransport())
    prod = td.deploy(
        target="prod",
        artifact_path=ARTIFACT_PATH,
        transport=_FakeTransport(state=_matching_state(artifact)),
    )

    assert dev.checksum == prod.checksum
    assert dev.target == "dev"
    assert prod.target == "prod"


def test_target_resolution_reads_the_environment_and_names_what_is_missing() -> None:
    with pytest.raises(td.DeployError) as raised:
        td.resolve_target("staging", env={"PULSE_TWENTY_STAGING_URL": "https://staging.invalid"})

    message = str(raised.value)
    assert "PULSE_TWENTY_STAGING_TOKEN" in message
    assert "PULSE_TWENTY_STAGING_URL" not in message


def test_an_unknown_target_is_refused() -> None:
    with pytest.raises(td.DeployError) as raised:
        td.resolve_target("laptop", env={})
    assert "laptop" in str(raised.value)


def test_a_credential_is_never_echoed() -> None:
    target = td.resolve_target(
        "dev", env={"PULSE_TWENTY_DEV_URL": "https://dev.invalid", "PULSE_TWENTY_DEV_TOKEN": FAKE_CRED}
    )
    assert FAKE_CRED not in repr(target)
    assert target.token == FAKE_CRED


def test_main_without_credentials_names_the_variables_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = td.main(["--target", "staging"], env={})

    printed = capsys.readouterr().out
    assert exit_code == 1
    assert "PULSE_TWENTY_STAGING_URL" in printed
    assert "PULSE_TWENTY_STAGING_TOKEN" in printed


def test_the_cli_builds_its_transport_from_the_resolved_target(env: dict[str, str]) -> None:
    """Constructing the client opens nothing — this test runs under `disable_socket`."""
    transport = td._build_transport("dev", env, dry_run=False)
    assert isinstance(transport, td.MetadataApiTransport)
    assert td._build_transport("dev", {}, dry_run=True) is None


def test_a_missing_artifact_file_is_a_finding(tmp_path: Path) -> None:
    assert td.validation_findings(tmp_path / "absent.json") == (f"{tmp_path / 'absent.json'} is missing",)


def test_a_read_failure_carries_the_status_and_no_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"record": {"name": SYNTHETIC_RECORD_VALUE}})

    transport = td.MetadataApiTransport(
        target=td.Target(name="dev", url="https://dev.invalid", token=FAKE_CRED),
        client=httpx.Client(base_url="https://dev.invalid", transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(td.TransportError) as raised:
        transport.read_state()

    assert raised.value.status == 503
    assert SYNTHETIC_RECORD_VALUE not in str(raised.value)


# --- Dry run -----------------------------------------------------------------------------------


def test_dry_run_sends_nothing(
    artifact: dict[str, Any], env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: "Dry-run sends nothing" — under `disable_socket`, with a fixture transport."""
    transport = _FakeTransport(state=_drifted_state(artifact))

    exit_code = td.main(["--target", "dev", "--dry-run"], env=env, transport=transport)

    assert exit_code == 0
    assert transport.sent == []
    assert transport.reads == 1
    printed = capsys.readouterr().out
    assert "update" in printed
    assert "noop" in printed


def test_offline_dry_run_plans_against_an_empty_target(artifact: dict[str, Any]) -> None:
    """No credentials, no transport: the plan is computed against the empty-state assumption."""
    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=None, dry_run=True)

    assert receipt.counts["create"] == len(artifact["operations"])
    assert receipt.dry_run is True


# --- Receipt containment -----------------------------------------------------------------------


def _failing_http_transport(status: int = 422) -> td.MetadataApiTransport:
    """The real transport over a scripted HTTP boundary whose error body carries record data."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(status, json={"error": "conflict", "record": {"name": SYNTHETIC_RECORD_VALUE}})

    return td.MetadataApiTransport(
        target=td.Target(name="dev", url="https://dev.invalid", token=FAKE_CRED),
        client=httpx.Client(base_url="https://dev.invalid", transport=httpx.MockTransport(handler)),
    )


def test_a_failed_operations_receipt_is_safe_to_attach(env: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: "A failed operation's receipt is safe to attach"."""
    transport = _failing_http_transport()

    exit_code = td.main(["--target", "dev"], env=env, transport=transport)

    printed = capsys.readouterr()
    assert exit_code == 1
    for stream in (printed.out, printed.err):
        assert SYNTHETIC_RECORD_VALUE not in stream
        assert "Testpatient" not in stream
    assert "422" in printed.out
    assert "createObject clinic" in printed.out


def test_a_transport_error_cannot_carry_a_body() -> None:
    """The containment is structural: there is no field on the error to leak."""
    error = td.TransportError(500)
    assert str(error) == "the target rejected the operation with status 500"
    assert not [name for name in vars(error) if name != "status"]


def test_the_receipt_carries_names_counts_and_the_checksum_only(artifact: dict[str, Any], env: dict[str, str]) -> None:
    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=_FakeTransport())
    body = json.dumps(receipt.to_dict())

    assert set(receipt.to_dict()) == {"target", "artifact", "checksum", "dryRun", "counts", "operations", "failure"}
    assert env["PULSE_TWENTY_DEV_TOKEN"] not in body
    assert receipt.checksum == td.artifact_checksum(ARTIFACT_PATH)
    assert len(receipt.operations) == len(artifact["operations"])


def test_the_failure_receipt_names_the_operation_and_status(artifact: dict[str, Any]) -> None:
    first = td.operation_name(artifact["operations"][0])
    transport = _FakeTransport(fail_on=first, fail_status=409)

    receipt = td.deploy(target="dev", artifact_path=ARTIFACT_PATH, transport=transport)

    assert receipt.failure == f"{first}: status 409"
    assert receipt.counts["create"] == 0
    # Fail fast: a field create behind a failed object create is guaranteed noise.
    assert len(transport.sent) == 1


# --- Transport shape ---------------------------------------------------------------------------


def test_the_transport_reads_and_writes_the_pinned_endpoints() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "rec-1", "universalIdentifier": "u-1", "nameSingular": "clinic"},
                    ]
                    if request.url.path.endswith("objects")
                    else []
                },
            )
        return httpx.Response(200, json={"data": {}})

    transport = td.MetadataApiTransport(
        target=td.Target(name="dev", url="https://dev.invalid", token=FAKE_CRED),
        client=httpx.Client(base_url="https://dev.invalid", transport=httpx.MockTransport(handler)),
    )
    state = transport.read_state()
    assert state["u-1"].record_id == "rec-1"
    assert "id" not in state["u-1"].payload

    transport.send("create", td.PlanItem(key="u-2", kind="createObject", name="createObject x", payload={"a": 1}))
    transport.send(
        "update",
        td.PlanItem(key="u-1", kind="createObject", name="createObject clinic", payload={"a": 1}, record_id="rec-1"),
    )

    assert ("POST", f"{td.METADATA_ROOT}/objects") in seen
    assert ("PATCH", f"{td.METADATA_ROOT}/objects/rec-1") in seen
    assert {method for method, _ in seen} == {"GET", "POST", "PATCH"}
    assert all(path.startswith(td.METADATA_ROOT) for _, path in seen)


def test_the_module_never_names_a_delete_verb() -> None:
    source = Path(td.__file__).read_text()
    assert "DELETE" not in source
    assert ".delete(" not in source
