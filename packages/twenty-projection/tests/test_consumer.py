"""The consumer loop: fixture queue → `pulse_core.consume` → the apply core (task 2.3).

Pins the twenty-projection spec scenarios owned by this task: a committed enrollment event
applies from the queue alone and its message is deleted only after the write succeeds ("An
event applies from the queue alone"); the same message delivered twice produces exactly one
write ("A redelivered message applies nothing twice"); the package imports no ledger database
driver and reads no ledger env var ("The projection holds no ledger credential"); and a
missing env var fails startup by name, never with a stack trace into boto3.

All data is synthetic: spine IDs and program codes only, never a name or demographic. The
queue and the Twenty REST surface are both fixtures — sockets are blocked by conftest.py.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import twenty_projection
from twenty_projection import consumer
from twenty_projection.apply import ProjectionRestClient
from twenty_projection.consumer import ConsumerConfig, ConsumerStartupError, resolve_config, run

PLURAL = "patientPrograms"
QUEUE_URL = "https://sqs.fixture/000000000000/twenty-projection"


# --- Fixtures: a scripted queue and a scripted Twenty sharing one journal ------------------------


class FixtureQueue:
    """A fake SQS client: scripted delivery batches, deletions recorded into a shared journal."""

    def __init__(self, deliveries: list[list[dict[str, Any]]], journal: list[tuple[str, str]]) -> None:
        self.deliveries = [list(batch) for batch in deliveries]
        self.journal = journal

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["QueueUrl"] == QUEUE_URL
        batch = self.deliveries.pop(0) if self.deliveries else []
        return {"Messages": batch}

    def delete_message(self, **kwargs: Any) -> None:
        assert kwargs["QueueUrl"] == QUEUE_URL
        self.journal.append(("delete", kwargs["ReceiptHandle"]))


class FixtureTwenty:
    """A fake Twenty REST surface: filtered listing, PATCHes journaled, scripted PATCH failures."""

    def __init__(
        self,
        records: list[dict[str, Any]],
        journal: list[tuple[str, str]],
        *,
        patch_script: list[int] | None = None,
    ) -> None:
        self.records = {str(record["id"]): dict(record) for record in records}
        self.journal = journal
        self.patch_script = list(patch_script or [])
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if request.method == "GET" and path == f"/rest/{PLURAL}":
            return self._list(request)
        if request.method == "PATCH" and path.startswith(f"/rest/{PLURAL}/"):
            return self._patch(request, path.rsplit("/", 1)[1])
        return httpx.Response(404, json={})

    def _list(self, request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        raw_filter = params.get("filter", [""])[0]
        predicates: dict[str, str] = {}
        for predicate in raw_filter.split(","):
            field, _, value = predicate.partition("[eq]:")
            predicates[field] = value
        matches = [
            record
            for record in self.records.values()
            if all(str(record.get(field)) == value for field, value in predicates.items())
        ]
        limit = int(params.get("limit", ["10"])[0])
        return httpx.Response(200, json={"data": {PLURAL: matches[:limit]}})

    def _patch(self, request: httpx.Request, record_id: str) -> httpx.Response:
        if self.patch_script:
            status = self.patch_script.pop(0)
            if status >= 400:
                return httpx.Response(status, json={"error": "synthetic failure body"})
        fields = json.loads(request.content)
        self.patches.append((record_id, fields))
        self.journal.append(("patch", record_id))
        self.records[record_id].update(fields)
        return httpx.Response(200, json={"data": {"updatePatientProgram": dict(self.records[record_id])}})


def board_record(record_id: str = "rec-1", *, subject: str = "pt-0001", program: str = "CCM") -> dict[str, Any]:
    return {
        "id": record_id,
        "canonicalPatientId": subject,
        "programCode": program,
        "lifecycleStatus": "PENDING_START",
        "lifecycleStatusAsOf": "2026-08-01T00:00:00+00:00",
        "projectionSeq": None,
    }


def enrollment_envelope(
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    to_state: str = "active",
    seq: int = 1,
    event_id: str = "evt-1",
    subject_type: str = "enrollment",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "enrollment.declared",
        "subject_type": subject_type,
        "subject_key": subject,
        "seq": seq,
        "effective_at": "2026-08-18T12:00:00+00:00",
        "payload": {"to_state": to_state, "program": program},
    }


def queue_message(envelope: dict[str, Any], *, receipt: str) -> dict[str, Any]:
    """An EventBridge-delivered message: the envelope rides whole inside `detail`."""
    return {"Body": json.dumps({"detail": envelope}), "ReceiptHandle": receipt}


def fixture_config() -> ConsumerConfig:
    token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
    return ConsumerConfig(
        target="dev",
        twenty_url="https://twenty.fixture",
        twenty_token=token,
        queue_url=QUEUE_URL,
    )


def run_fixture(
    twenty: FixtureTwenty,
    queue: FixtureQueue,
    *,
    iterations: int = 1,
) -> None:
    config = fixture_config()
    with ProjectionRestClient(config.twenty_url, token=config.twenty_token, transport=twenty.transport()) as client:
        run(config, client=client, sqs_client=queue, iterations=iterations)


# --- Spec: An event applies from the queue alone --------------------------------------------------


def test_event_applies_from_the_queue_alone() -> None:
    """A committed event on the fixture queue writes status, as-of, and watermark, then deletes."""
    journal: list[tuple[str, str]] = []
    twenty = FixtureTwenty([board_record()], journal)
    queue = FixtureQueue([[queue_message(enrollment_envelope(seq=7), receipt="rh-1")]], journal)

    run_fixture(twenty, queue)

    assert len(twenty.patches) == 1
    record_id, fields = twenty.patches[0]
    assert record_id == "rec-1"
    assert fields == {
        "lifecycleStatus": "ACTIVE",
        "lifecycleStatusAsOf": "2026-08-18T12:00:00+00:00",
        "projectionSeq": 7,
    }
    # Deleted, and only after the write: the patch precedes the delete in the shared journal.
    assert journal == [("patch", "rec-1"), ("delete", "rh-1")]


def test_failed_write_leaves_the_message_on_the_queue() -> None:
    """Delete only after success: a non-retryable write failure deletes nothing."""
    journal: list[tuple[str, str]] = []
    twenty = FixtureTwenty([board_record()], journal, patch_script=[400])
    queue = FixtureQueue([[queue_message(enrollment_envelope(), receipt="rh-fail")]], journal)

    run_fixture(twenty, queue)

    assert twenty.patches == []
    assert journal == []  # no successful patch, and no delete


# --- Spec: A redelivered message applies nothing twice --------------------------------------------


def test_redelivered_message_applies_nothing_twice() -> None:
    """The same message delivered on two passes: one write, both copies deleted."""
    journal: list[tuple[str, str]] = []
    envelope = enrollment_envelope(event_id="evt-dup", seq=3)
    twenty = FixtureTwenty([board_record()], journal)
    queue = FixtureQueue(
        [
            [queue_message(envelope, receipt="rh-first")],
            [queue_message(envelope, receipt="rh-second")],
        ],
        journal,
    )

    run_fixture(twenty, queue, iterations=2)

    assert len(twenty.patches) == 1
    assert journal == [("patch", "rec-1"), ("delete", "rh-first"), ("delete", "rh-second")]


# --- Board-relevance filter ------------------------------------------------------------------------


def test_non_board_subject_is_skipped_and_consumed(caplog: pytest.LogCaptureFixture) -> None:
    """An event for a non-board subject writes nothing, is deleted, and logs identifiers only."""
    journal: list[tuple[str, str]] = []
    twenty = FixtureTwenty([board_record()], journal)
    queue = FixtureQueue(
        [[queue_message(enrollment_envelope(event_id="evt-other", subject_type="verdict"), receipt="rh-skip")]],
        journal,
    )

    with caplog.at_level("DEBUG", logger="twenty_projection.consumer"):
        run_fixture(twenty, queue)

    assert twenty.patches == []
    assert journal == [("delete", "rh-skip")]
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "evt-other" in logged
    assert "active" not in logged  # never a payload value
    assert "2026-08-18T12:00:00" not in logged


# --- Spec: The projection holds no ledger credential ------------------------------------------------

#: The env vars the consumer is allowed to read — the Twenty credential and the queue, nothing else.
ALLOWED_ENV_PREFIXES = ("PULSE_TWENTY_",)
ALLOWED_ENV_NAMES = frozenset({"SQS_QUEUE_URL"})

#: Ledger database drivers and the ledger package itself: importing any of these is holding a path
#: to the ledger. boto3 is queue transport, not a ledger driver, and is imported lazily by
#: pulse_core.consume only.
FORBIDDEN_IMPORTS = frozenset({"psycopg", "psycopg2", "sqlalchemy", "asyncpg", "pulse_ledger"})

#: Env var fragments that would carry a ledger DSN or writer credential.
FORBIDDEN_ENV_FRAGMENTS = ("DATABASE_URL", "PULSE_LEDGER", "DSN", "WRITER_TOKEN")


def package_sources() -> list[Path]:
    assert twenty_projection.__file__ is not None
    pkg_root = Path(twenty_projection.__file__).resolve().parent
    return sorted(pkg_root.rglob("*.py"))


def test_no_ledger_driver_import_anywhere_in_the_package() -> None:
    for source_path in package_sources():
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root not in FORBIDDEN_IMPORTS, f"{source_path.name} imports ledger-side module {name!r}"


def code_string_literals(tree: ast.Module) -> list[str]:
    """Every string constant that is code, not prose: docstrings are dropped before the walk."""
    prose: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                prose.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    ]


def test_no_ledger_env_var_read_anywhere_in_the_package() -> None:
    """No code-level string in the package names a ledger DSN or writer-token variable."""
    for source_path in package_sources():
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for literal in code_string_literals(tree):
            for fragment in FORBIDDEN_ENV_FRAGMENTS:
                assert fragment not in literal, (
                    f"{source_path.name} carries ledger env fragment {fragment!r} in {literal!r}"
                )


def test_consumer_env_surface_is_exactly_the_twenty_credential_and_the_queue() -> None:
    url_var, token_var = consumer.env_var_names("dev")
    assert url_var == "PULSE_TWENTY_DEV_URL"
    assert token_var == "PULSE_TWENTY_DEV_TOKEN"  # noqa: S105 — a variable name, not a secret
    assert consumer.QUEUE_URL_VAR == "SQS_QUEUE_URL"
    for name in (url_var, token_var):
        assert name.startswith(ALLOWED_ENV_PREFIXES)
    assert consumer.QUEUE_URL_VAR in ALLOWED_ENV_NAMES


# --- Startup: a missing env var fails by name --------------------------------------------------------


def test_missing_env_vars_fail_startup_by_name() -> None:
    with pytest.raises(ConsumerStartupError) as excinfo:
        resolve_config("dev", {})
    message = str(excinfo.value)
    assert "PULSE_TWENTY_DEV_URL" in message
    assert "PULSE_TWENTY_DEV_TOKEN" in message
    assert "SQS_QUEUE_URL" in message


def test_one_missing_env_var_is_named_alone() -> None:
    env = {
        "PULSE_TWENTY_DEV_URL": "https://twenty.fixture",
        "PULSE_TWENTY_DEV_TOKEN": "fixture-token",
    }
    with pytest.raises(ConsumerStartupError) as excinfo:
        resolve_config("dev", env)
    message = str(excinfo.value)
    assert "SQS_QUEUE_URL" in message
    assert "PULSE_TWENTY_DEV_URL" not in message


def test_empty_env_var_counts_as_missing() -> None:
    env = {
        "PULSE_TWENTY_DEV_URL": "https://twenty.fixture",
        "PULSE_TWENTY_DEV_TOKEN": "",
        "SQS_QUEUE_URL": QUEUE_URL,
    }
    with pytest.raises(ConsumerStartupError) as excinfo:
        resolve_config("dev", env)
    assert "PULSE_TWENTY_DEV_TOKEN" in str(excinfo.value)


def test_resolve_config_reads_the_target_scoped_credential() -> None:
    env = {
        "PULSE_TWENTY_DEV_URL": "https://twenty.fixture",
        "PULSE_TWENTY_DEV_TOKEN": "fixture-token",
        "SQS_QUEUE_URL": QUEUE_URL,
    }
    config = resolve_config("dev", env)
    assert config == fixture_config()


def test_main_fails_startup_by_name(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """`task projection:consume TARGET=dev` in a bare environment: exit 2, every var named."""
    for name in ("PULSE_TWENTY_DEV_URL", "PULSE_TWENTY_DEV_TOKEN", "SQS_QUEUE_URL"):
        monkeypatch.delenv(name, raising=False)

    assert consumer.main(["--target", "dev"]) == 2

    captured = capsys.readouterr()
    assert "PULSE_TWENTY_DEV_URL" in captured.err
    assert "PULSE_TWENTY_DEV_TOKEN" in captured.err
    assert "SQS_QUEUE_URL" in captured.err
