"""`scripts/demo/demo5_preflight.py` — the three `--live` preconditions, checked offline here
with fake transports: the image probe reads 404 as stale and anything else as served, the schema
check wants exactly ``0005``, the seeded-card scan pages and matches on both fields, and no
message ever carries a credential value. Plus the smoke-parse contract every demo script keeps.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "demo" / "demo5_preflight.py"
spec = importlib.util.spec_from_file_location("demo5_preflight", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight  # dataclasses resolve annotations through sys.modules (3.14)
spec.loader.exec_module(preflight)

TOKEN = "tok-preflight-test-0001"  # noqa: S105 — synthetic, asserted absent from every message


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_help_exits_zero() -> None:
    completed = subprocess.run(  # noqa: S603 — fixed argv, our own script
        [sys.executable, str(SCRIPT_PATH), "--help"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    assert "preflight" in completed.stdout


def test_environment_check_names_missing_variables_only() -> None:
    results = preflight.run_preflight({})
    assert [r.ok for r in results] == [False]
    assert "PULSE_CORE_REPLAY_TOKEN" in results[0].message
    assert TOKEN not in results[0].message


@pytest.mark.parametrize(("status", "expected_ok"), [(404, False), (200, True), (401, True), (403, True)])
def test_api_image_probe_reads_only_404_as_stale(status: int, expected_ok: bool) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(status)

    result = preflight.check_api_current(_client(handler), "https://ledger.example", TOKEN)
    assert result.ok is expected_ok
    assert seen["path"] == preflight.PROBE_SUBJECT_PATH
    assert TOKEN not in result.message


def test_api_image_probe_names_transport_errors_without_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = preflight.check_api_current(_client(handler), "https://ledger.example", TOKEN)
    assert result.ok is False
    assert "PULSE_LEDGER_API_URL" in result.message
    assert "boom" not in result.message


@pytest.mark.parametrize(("head", "expected_ok"), [("0005", True), ("0004", False), ("", False)])
def test_schema_check_wants_the_exact_head(head: str, expected_ok: bool) -> None:
    result = preflight.check_migration(lambda: head)
    assert result.ok is expected_ok
    if not expected_ok:
        assert "0005" in result.message


def test_schema_check_names_query_failures_by_type_only() -> None:
    def boom() -> str:
        raise RuntimeError("password=leaky")

    result = preflight.check_migration(boom)
    assert result.ok is False
    assert "RuntimeError" in result.message
    assert "leaky" not in result.message


def _board_pages(records_by_page: list[list[dict[str, str]]]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/rest/{preflight.BOARD_OBJECT_PLURAL}")
        cursor = request.url.params.get("starting_after")
        index = 0 if cursor is None else int(cursor.removeprefix("rec-")) + 1
        page = records_by_page[index] if index < len(records_by_page) else []
        body = {
            "data": {preflight.BOARD_OBJECT_PLURAL: page},
            "pageInfo": {"hasNextPage": index + 1 < len(records_by_page)},
        }
        return httpx.Response(200, json=body)

    return handler


def test_seeded_card_found_on_a_later_page() -> None:
    pages = [
        [{"id": "rec-0", "canonicalPatientId": "other", "programCode": "demo5"}],
        [{"id": "rec-1", "canonicalPatientId": "fx-1", "programCode": "demo5"}],
    ]
    result = preflight.check_seeded_card(_client(_board_pages(pages)), "https://twenty.example", TOKEN, "fx-1")
    assert result.ok is True
    assert "2 scanned" in result.message


def test_seeded_card_requires_both_fields() -> None:
    pages = [[{"id": "rec-0", "canonicalPatientId": "fx-1", "programCode": "other"}]]
    result = preflight.check_seeded_card(_client(_board_pages(pages)), "https://twenty.example", TOKEN, "fx-1")
    assert result.ok is False
    assert "programCode=demo5" in result.message
    assert TOKEN not in result.message


def test_board_reachable_replaces_the_card_check_for_a_run_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {preflight.BOARD_OBJECT_PLURAL: []}})

    result = preflight.check_board_reachable(_client(handler), "https://twenty.example", TOKEN, "r1")
    assert result.ok is True
    assert result.name == "seeded-card"
    assert "r1" in result.message
    assert TOKEN not in result.message


def test_board_reachable_names_transport_errors_by_type_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    result = preflight.check_board_reachable(_client(handler), "https://twenty.example", TOKEN, "r1")
    assert result.ok is False
    assert "ConnectError" in result.message


def test_fixture_subject_key_comes_from_the_committed_consent_row(tmp_path: Path) -> None:
    fixture = tmp_path / "row.json"
    fixture.write_text(json.dumps({"subject_key": "fx-9"}))
    assert preflight.fixture_subject_key(fixture) == "fx-9"
    assert preflight.fixture_subject_key().startswith("brook-fx-demo5")


def test_run_preflight_reports_every_check_and_exit_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == preflight.PROBE_SUBJECT_PATH:
            return httpx.Response(404)
        return httpx.Response(
            200, json={"data": {preflight.BOARD_OBJECT_PLURAL: []}, "pageInfo": {"hasNextPage": False}}
        )

    env = {
        "PULSE_LEDGER_API_URL": "https://ledger.example",
        "PULSE_CORE_REPLAY_TOKEN": TOKEN,
        "DATABASE_URL": "postgresql://user:leaky@db.example/ledger",
        "PULSE_TWENTY_DEV_URL": "https://twenty.example",
        "PULSE_TWENTY_DEV_TOKEN": TOKEN,
    }
    results = preflight.run_preflight(env, client=_client(handler), fetch_head=lambda: "0005", subject_key="fx-1")
    assert [r.name for r in results] == ["api-image", "ledger-schema", "seeded-card"]
    assert [r.ok for r in results] == [False, True, False]
    joined = " ".join(r.message for r in results)
    assert "leaky" not in joined and TOKEN not in joined
