"""Seed-loader tests (twenty-dev-instance 2.5) — every twenty-seed-load claim, on a fake client.

No test here reaches a Twenty instance: sockets are disabled module-wide. The scripted states the
work order names are the `_FakeRecords` constructions below — empty, already-seeded, drifted, one
carrying a workspace record the projection does not describe — plus the checksum-mismatch and
board-completeness refusals, which never reach a transport at all.

Every value below is synthetic. `SYNTHETIC_FIELD_VALUE` exists so a receipt echoing workspace
content is a test failure rather than a review question.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from pulse_core import twenty_seed as ts
from pulse_core.twenty_deploy import DeployError, RemoteRecord, Target, TransportError
from pulse_core.twenty_metadata import ARTIFACT_PATH
from pytest_socket import disable_socket, enable_socket

#: A value that would be workspace data on a live instance. Synthetic — used only inside fakes.
SYNTHETIC_FIELD_VALUE = "Wilhelmina Testpatient (MRN SYN-000123)"

FAKE_CRED = "t-dev"


@pytest.fixture(autouse=True)
def _no_sockets() -> Iterator[None]:
    disable_socket()
    yield
    enable_socket()


@pytest.fixture(scope="module")
def projection() -> ts.Projection:
    return ts.load_projection(ts.SEED_PATH)


@pytest.fixture
def env() -> dict[str, str]:
    return {"PULSE_TWENTY_DEV_URL": "https://dev.invalid", "PULSE_TWENTY_DEV_TOKEN": FAKE_CRED}


class _FakeRecords:
    """A scripted workspace: per-object remote records, a recorder, an optional scripted failure."""

    def __init__(
        self,
        state: dict[str, list[RemoteRecord]] | None = None,
        fail_on: str | None = None,
        fail_status: int = 429,
    ) -> None:
        self.state: dict[str, list[RemoteRecord]] = state or {}
        self.fail_on = fail_on
        self.fail_status = fail_status
        self.created: list[tuple[str, int]] = []  # (plural, chunk size) per create_batch call
        self.patched: list[tuple[str, str]] = []  # (plural, record id) per patch call
        self._minted = 0

    def list_records(self, plural: str) -> tuple[RemoteRecord, ...]:
        return tuple(self.state.get(plural, ()))

    def create_batch(self, plural: str, payloads: tuple[Mapping[str, Any], ...]) -> tuple[RemoteRecord, ...]:
        if self.fail_on == plural:
            raise TransportError(self.fail_status)
        self.created.append((plural, len(payloads)))
        minted = []
        for payload in payloads:
            self._minted += 1
            minted.append(RemoteRecord(record_id=f"{plural}-{self._minted}", payload=dict(payload)))
        self.state.setdefault(plural, []).extend(minted)
        return tuple(minted)

    def patch(self, plural: str, record_id: str, payload: Mapping[str, Any]) -> None:
        self.patched.append((plural, record_id))


def _seeded_state(projection: ts.Projection) -> dict[str, list[RemoteRecord]]:
    """The workspace state after this exact projection has been loaded into it."""
    fake = _FakeRecords()
    ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
    return fake.state


def _write_projection(path: Path, records: dict[str, Any], checksum: str | None = None) -> Path:
    body = {
        "format": ts.SEED_FORMAT,
        "checksum": ts.records_checksum(records) if checksum is None else checksum,
        "records": records,
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True))
    return path


# --- The committed projection ---------------------------------------------------------------------


class TestCommittedProjection:
    def test_loads_offline_with_no_generator_toolchain(self, projection: ts.Projection) -> None:
        """Spec: "Seeding from a fresh clone needs no generator" — the file loads, sockets off."""
        assert projection.checksum == ts.records_checksum(projection.records)

    def test_carries_about_twenty_patients(self, projection: ts.Projection) -> None:
        assert len(projection.records["patients"]) == 20

    def test_spine_ids_are_minted_from_the_generator_record_ids(self, projection: ts.Projection) -> None:
        """Spec: repeated derivation from the generator's record identifier yields the same value."""
        for record in projection.records["patients"]:
            source = record["sourceRecordId"]
            assert record["fields"]["canonicalPatientId"] == ts.mint_canonical_patient_id(source)

    def test_natural_keys_are_unique_per_object(self, projection: ts.Projection) -> None:
        for obj in ts.SEED_OBJECTS:
            keys = [ts.natural_key(obj, record["fields"]) for record in projection.records[obj.plural]]
            assert len(keys) == len(set(keys)), f"{obj.plural} carries a duplicate natural key"

    def test_every_relation_resolves_inside_the_projection(self, projection: ts.Projection) -> None:
        patients = {r["fields"]["canonicalPatientId"] for r in projection.records["patients"]}
        programs = {r["fields"]["code"] for r in projection.records["programs"]}
        for record in projection.records["patientPrograms"]:
            assert record["fields"]["canonicalPatientId"] in patients
            assert record["fields"]["programCode"] in programs

    def test_statuses_are_values_the_deployed_model_accepts(self, projection: ts.Projection) -> None:
        artifact = json.loads(ARTIFACT_PATH.read_text())
        options = {
            op["name"]: {option["value"] for option in op["options"]}
            for op in artifact["operations"]
            if op["operation"] == "createField" and op.get("objectNameSingular") == "patientProgram"
            if op["name"] in ("lifecycleStatus", "qualificationStatus")
        }
        for record in projection.records["patientPrograms"]:
            assert record["fields"]["lifecycleStatus"] in options["lifecycleStatus"]
            assert record["fields"]["qualificationStatus"] in options["qualificationStatus"]

    def test_every_board_record_carries_both_as_of_stamps(self, projection: ts.Projection) -> None:
        """Spec: "Every seeded board record is immediately draggable" — non-null as-of stamps."""
        for record in projection.records["patientPrograms"]:
            for stamp in ts.BOARD_AS_OF_FIELDS["patientPrograms"]:
                assert record["fields"].get(stamp), f"a patientProgram record has no {stamp}"

    def test_board_statuses_cover_more_than_one_column(self, projection: ts.Projection) -> None:
        statuses = {r["fields"]["lifecycleStatus"] for r in projection.records["patientPrograms"]}
        assert len(statuses) > 1, "every card in one column makes a drag demo trivial"


# --- Refusals before any transport ------------------------------------------------------------------


class TestProjectionRefusals:
    def test_checksum_mismatch_is_refused_and_named(self, tmp_path: Path, projection: ts.Projection) -> None:
        """Spec: "The projection is verified before use"."""
        records = json.loads(json.dumps(dict(projection.records)))
        path = _write_projection(tmp_path / "seed.json", records, checksum="0" * 64)
        with pytest.raises(DeployError) as raised:
            ts.load_projection(path)
        assert "checksum" in str(raised.value)
        assert "0" * 64 in str(raised.value)

    def test_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DeployError):
            ts.load_projection(tmp_path / "absent.json")

    def test_unparseable_file_is_refused(self, tmp_path: Path) -> None:
        broken = tmp_path / "seed.json"
        broken.write_text("{not json")
        with pytest.raises(DeployError):
            ts.load_projection(broken)

    def test_unknown_format_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "seed.json"
        path.write_text(json.dumps({"format": "something-else@9", "checksum": "0" * 64, "records": {}}))
        with pytest.raises(DeployError):
            ts.load_projection(path)

    def test_board_record_missing_its_as_of_stamp_is_refused(self, tmp_path: Path) -> None:
        """A record that would refuse its first drag never reaches the workspace."""
        records = {
            "programs": [{"fields": {"code": "rpm", "name": "RPM"}}],
            "patients": [{"fields": {"canonicalPatientId": "cp-1", "name": {"firstName": "A", "lastName": "B"}}}],
            "patientPrograms": [
                {
                    "fields": {
                        "canonicalPatientId": "cp-1",
                        "programCode": "rpm",
                        "lifecycleStatus": "active",
                        "lifecycleStatusAsOf": None,
                        "qualificationStatus": "open",
                        "qualificationStatusAsOf": "2026-08-01T00:00:00Z",
                    }
                }
            ],
        }
        path = _write_projection(tmp_path / "seed.json", records)
        with pytest.raises(DeployError) as raised:
            ts.load_projection(path)
        assert "lifecycleStatusAsOf" in str(raised.value)

    def test_seed_refuses_a_bad_projection_before_reading_the_target(self, tmp_path: Path) -> None:
        fake = _FakeRecords()
        broken = tmp_path / "seed.json"
        broken.write_text("{not json")
        with pytest.raises(DeployError):
            ts.seed(target="dev", source_path=broken, transport=fake)
        assert fake.created == []
        assert fake.patched == []


# --- Idempotence -------------------------------------------------------------------------------------


class TestIdempotence:
    def test_empty_workspace_gets_every_record_created(self, projection: ts.Projection) -> None:
        fake = _FakeRecords()
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        assert receipt.failure is None
        for obj in ts.SEED_OBJECTS:
            expected = len(projection.records[obj.plural])
            assert receipt.objects[obj.plural] == {"create": expected, "update": 0, "noop": 0}
        assert fake.patched == []

    def test_second_run_changes_nothing(self, projection: ts.Projection) -> None:
        """Spec: "A second run changes nothing" — all-unchanged, no write issued."""
        fake = _FakeRecords(state=_seeded_state(projection))
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        assert fake.created == []
        assert fake.patched == []
        for obj in ts.SEED_OBJECTS:
            expected = len(projection.records[obj.plural])
            assert receipt.objects[obj.plural] == {"create": 0, "update": 0, "noop": expected}

    def test_drifted_field_is_patched_back(self, projection: ts.Projection) -> None:
        """Spec: "A drifted field is patched back" — exactly that record, reported as updated."""
        state = _seeded_state(projection)
        drifted = state["patientPrograms"][0]
        state["patientPrograms"][0] = RemoteRecord(
            record_id=drifted.record_id,
            payload=dict(drifted.payload) | {"lifecycleStatus": "ended"},
        )
        fake = _FakeRecords(state=state)
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        assert fake.created == []
        assert fake.patched == [("patientPrograms", drifted.record_id)]
        assert receipt.objects["patientPrograms"]["update"] == 1

    def test_workspace_record_outside_the_projection_survives(self, projection: ts.Projection) -> None:
        """Spec: "Workspace records outside the projection survive" — and no delete verb exists."""
        state = _seeded_state(projection)
        stranger = RemoteRecord(record_id="patients-stranger", payload={"canonicalPatientId": "someone-else"})
        state["patients"] = [*state["patients"], stranger]
        fake = _FakeRecords(state=state)
        ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        assert fake.created == []
        assert fake.patched == []
        assert stranger in fake.state["patients"]
        assert not hasattr(fake, "delete"), "the transport protocol must expose no delete verb"

    def test_server_side_extra_keys_are_not_drift(self, projection: ts.Projection) -> None:
        """Base columns the instance adds (`createdAt`, ...) never make a matching record dirty."""
        state = _seeded_state(projection)
        state["patients"] = [
            RemoteRecord(record_id=r.record_id, payload=dict(r.payload) | {"createdAt": "2026-08-16T00:00:00Z"})
            for r in state["patients"]
        ]
        fake = _FakeRecords(state=state)
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        assert receipt.objects["patients"]["noop"] == len(projection.records["patients"])

    def test_child_records_reference_parents_created_in_the_same_run(self, projection: ts.Projection) -> None:
        """patientPrograms created into an empty workspace carry the ids minted for their parents."""
        fake = _FakeRecords()
        ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        patient_ids = {r.record_id for r in fake.state["patients"]}
        program_ids = {r.record_id for r in fake.state["programs"]}
        for record in fake.state["patientPrograms"]:
            assert record.payload["patientId"] in patient_ids
            assert record.payload["programId"] in program_ids


# --- Limits ------------------------------------------------------------------------------------------


class TestLimits:
    def test_creates_are_chunked_to_the_per_call_limit(self, tmp_path: Path) -> None:
        """Spec: "A large population is loaded within rate limits" — 70 patients → 60 + 10."""
        records = {
            "programs": [],
            "patients": [
                {"fields": {"canonicalPatientId": f"cp-{i:03d}", "name": {"firstName": "S", "lastName": f"T{i}"}}}
                for i in range(70)
            ],
            "patientPrograms": [],
        }
        path = _write_projection(tmp_path / "seed.json", records)
        fake = _FakeRecords()
        receipt = ts.seed(target="dev", source_path=path, transport=fake)
        assert fake.created == [("patients", 60), ("patients", 10)]
        assert receipt.objects["patients"]["create"] == 70

    def test_pacer_spaces_requests_to_the_per_minute_limit(self) -> None:
        clock = iter([0.0, 0.6, 0.7, 1.2]).__next__
        slept: list[float] = []
        pacer = ts.Pacer(per_minute=100, sleep=slept.append, clock=clock)
        pacer.wait()  # first request goes straight through
        pacer.wait()  # a full 0.6s interval has already passed — no sleep
        pacer.wait()  # only 0.1s passed — must sleep the remaining 0.5
        assert slept == [pytest.approx(0.5)]

    def test_pacer_interval_matches_the_instance_limit(self) -> None:
        assert ts.MAX_RECORDS_PER_CALL == 60
        assert ts.MAX_REQUESTS_PER_MINUTE == 100


# --- Receipt containment ------------------------------------------------------------------------------


class TestReceipt:
    def test_receipt_carries_no_record_ids_or_field_values(self, projection: ts.Projection) -> None:
        """Spec: "A receipt carries no workspace content"."""
        state = _seeded_state(projection)
        drifted = state["patientPrograms"][0]
        state["patientPrograms"][0] = RemoteRecord(
            record_id="rec-do-not-echo",
            payload=dict(drifted.payload) | {"lifecycleStatus": SYNTHETIC_FIELD_VALUE},
        )
        fake = _FakeRecords(state=state)
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        dumped = json.dumps(receipt.to_dict())
        assert "rec-do-not-echo" not in dumped
        assert SYNTHETIC_FIELD_VALUE not in dumped
        for record in projection.records["patients"]:
            assert record["fields"]["canonicalPatientId"] not in dumped

    def test_receipt_names_source_checksum_and_counts(self, projection: ts.Projection) -> None:
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=_FakeRecords())
        assert receipt.target == "dev"
        assert receipt.checksum == projection.checksum
        assert set(receipt.objects) == {obj.plural for obj in ts.SEED_OBJECTS}

    def test_failure_names_the_object_and_status_only(self, projection: ts.Projection) -> None:
        fake = _FakeRecords(fail_on="patients", fail_status=429)
        receipt = ts.seed(target="dev", source_path=ts.SEED_PATH, transport=fake)
        assert receipt.failure == "patients: status 429"
        assert receipt.objects["patients"]["create"] == 0  # nothing went out for the failed object


# --- Transport ----------------------------------------------------------------------------------------


class TestRestTransport:
    """The real HTTP transport against `httpx.MockTransport` — shape and body-containment claims."""

    def _transport(self, handler: Any) -> ts.RestRecordsTransport:
        target = Target(name="dev", url="https://dev.invalid", token=FAKE_CRED)
        client = httpx.Client(
            base_url=target.url,
            transport=httpx.MockTransport(handler),
            headers={"Authorization": f"Bearer {target.token}"},
        )
        return ts.RestRecordsTransport(target, client=client, pacer=ts.Pacer(sleep=lambda _: None))

    def test_list_records_paginates_and_strips_ids_into_record_ids(self) -> None:
        pages = [
            {
                "data": {"patients": [{"id": "r1", "canonicalPatientId": "cp-1"}]},
                "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
            },
            {
                "data": {"patients": [{"id": "r2", "canonicalPatientId": "cp-2"}]},
                "pageInfo": {"hasNextPage": False},
            },
        ]
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, json=pages[len(calls) - 1])

        records = self._transport(handler).list_records("patients")
        assert [r.record_id for r in records] == ["r1", "r2"]
        assert all("id" not in r.payload for r in records)
        assert "starting_after=c1" in calls[1]

    def test_create_batch_posts_to_the_batch_endpoint(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json={"data": {"patients": [{"id": "r1", "canonicalPatientId": "cp-1"}]}})

        created = self._transport(handler).create_batch("patients", ({"canonicalPatientId": "cp-1"},))
        assert seen[0].method == "POST"
        assert seen[0].url.path == "/rest/batch/patients"
        assert created[0].record_id == "r1"

    def test_patch_addresses_one_record(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        self._transport(handler).patch("patients", "r1", {"mrn": "SYN-0001"})
        assert seen[0].method == "PATCH"
        assert seen[0].url.path == "/rest/patients/r1"

    def test_a_failing_response_body_never_reaches_the_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"error": SYNTHETIC_FIELD_VALUE})

        with pytest.raises(TransportError) as raised:
            self._transport(handler).list_records("patients")
        assert raised.value.status == 422
        assert SYNTHETIC_FIELD_VALUE not in str(raised.value)


# --- CLI ---------------------------------------------------------------------------------------------


class TestCli:
    def test_dry_run_with_no_credentials_plans_against_an_empty_workspace(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = ts.main(["--target", "dev", "--dry-run"], env={})
        receipt = json.loads(capsys.readouterr().out)
        assert code == 0
        assert receipt["dryRun"] is True
        assert receipt["objects"]["patients"]["create"] == 20

    def test_apply_without_credentials_is_refused(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = ts.main(["--target", "dev"], env={})
        out = capsys.readouterr().out
        assert code == 1
        assert "PULSE_TWENTY_DEV_URL" in out

    def test_unknown_target_is_refused_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            ts.main(["--target", "sandbox"], env={})

    def test_apply_with_injected_transport_prints_the_receipt(
        self, env: dict[str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = ts.main(["--target", "dev"], env=env, transport=_FakeRecords())
        receipt = json.loads(capsys.readouterr().out)
        assert code == 0
        assert receipt["failure"] is None

    def test_a_transport_failure_exits_nonzero(self, env: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
        code = ts.main(["--target", "dev"], env=env, transport=_FakeRecords(fail_on="programs"))
        receipt = json.loads(capsys.readouterr().out)
        assert code == 1
        assert receipt["failure"] == "programs: status 429"

    def test_checksum_mismatch_exits_nonzero_naming_the_mismatch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], projection: ts.Projection
    ) -> None:
        records = json.loads(json.dumps(dict(projection.records)))
        path = _write_projection(tmp_path / "seed.json", records, checksum="0" * 64)
        code = ts.main(["--target", "dev", "--source", str(path), "--dry-run"], env={})
        assert code == 1
        assert "checksum" in capsys.readouterr().out
