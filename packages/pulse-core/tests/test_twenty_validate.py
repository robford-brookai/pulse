"""Validator tests (pulse-app-scaffold 2.3) — every check passes the tree and rejects a break.

Two obligations per validator, and both matter equally: it passes the committed tree (otherwise
`task check` is red on arrival), and it rejects a *minimally* broken input (otherwise it passes
everything and gates nothing). Each break below is one mutation of the real committed data — a
drifted artifact, one deleted UID, one option the catalog does not carry, one option value
changed on the TypeScript side only.

Sockets are disabled module-wide for the same reason as the generator's suite: validation reads
files and nothing else.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pulse_core import twenty_metadata as tmg
from pulse_core import twenty_model as tm
from pulse_core import twenty_validate as tv
from pulse_core.catalog_gen import Catalog, load_catalog
from pytest_socket import disable_socket, enable_socket


@pytest.fixture(autouse=True)
def _no_sockets() -> Iterator[None]:
    disable_socket()
    yield
    enable_socket()


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog()


@pytest.fixture(scope="module")
def uid_map() -> dict[str, str]:
    return tm.load_uid_map()


@pytest.fixture(scope="module")
def committed() -> dict[Path, str]:
    return tv.read_committed()


@pytest.fixture(scope="module")
def artifact(committed: dict[Path, str]) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(committed[tmg.ARTIFACT_PATH])
    return loaded


@pytest.fixture(scope="module")
def options_ts(committed: dict[Path, str]) -> str:
    return committed[tmg.OPTIONS_PATH]


def _field_op(artifact: dict[str, Any], object_name: str, field_name: str) -> dict[str, Any]:
    """The committed `createField` operation for one field, as a mutable copy's member."""
    for operation in artifact["operations"]:
        if (
            operation["operation"] == "createField"
            and operation["objectNameSingular"] == object_name
            and operation["name"] == field_name
        ):
            return operation
    pytest.fail(f"no createField operation for {object_name}.{field_name}")


# --- The committed tree passes -----------------------------------------------------------------


def test_the_committed_tree_validates_clean(catalog: Catalog, uid_map: dict[str, str]) -> None:
    findings = tv.validate(tm.TWENTY_MODEL, catalog, uid_map)
    assert findings == (), "\n".join(findings)


def test_the_cli_exits_zero_on_the_committed_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert tv.main([]) == 0
    assert "valid" in capsys.readouterr().out


def test_every_validator_is_reached_by_validate(catalog: Catalog, uid_map: dict[str, str]) -> None:
    """A validator nobody calls gates nothing — the aggregate names each check it ran."""
    ran = tv.validate_verbose(tm.TWENTY_MODEL, catalog, uid_map)
    assert set(ran) == set(tv.CHECK_NAMES)


# --- Schema ------------------------------------------------------------------------------------


def test_schema_accepts_the_committed_artifact(artifact: dict[str, Any]) -> None:
    assert tv.check_schema(artifact) == ()


def test_schema_rejects_an_unknown_operation_kind(artifact: dict[str, Any]) -> None:
    broken = copy.deepcopy(artifact)
    broken["operations"][0]["operation"] = "dropObject"
    findings = tv.check_schema(broken)
    assert findings, "an unknown operation kind passed schema validation"


def test_schema_rejects_a_missing_required_key(artifact: dict[str, Any]) -> None:
    broken = copy.deepcopy(artifact)
    del broken["operations"][0]["nameSingular"]
    assert any("nameSingular" in finding for finding in tv.check_schema(broken))


def test_schema_rejects_an_unknown_key(artifact: dict[str, Any]) -> None:
    """`extra="forbid"`: a key the deploy step will not read is a silent no-op in production."""
    broken = copy.deepcopy(artifact)
    broken["operations"][0]["applyImmediately"] = True
    assert any("applyImmediately" in finding for finding in tv.check_schema(broken))


def test_schema_rejects_a_non_canonical_identifier(artifact: dict[str, Any]) -> None:
    broken = copy.deepcopy(artifact)
    broken["operations"][0]["universalIdentifier"] = "not-a-uuid"
    assert any("universalIdentifier" in finding for finding in tv.check_schema(broken))


def test_schema_rejects_a_missing_top_level_key(artifact: dict[str, Any]) -> None:
    broken = copy.deepcopy(artifact)
    del broken["catalogVersion"]
    assert any("catalogVersion" in finding for finding in tv.check_schema(broken))


# --- Staleness ---------------------------------------------------------------------------------


def test_the_committed_surfaces_are_current(
    committed: dict[Path, str], catalog: Catalog, uid_map: dict[str, str]
) -> None:
    rendered = tmg.generate(tm.TWENTY_MODEL, catalog, uid_map)
    assert tv.check_current(committed, rendered) == ()


def test_a_drifted_committed_artifact_is_named_stale(
    committed: dict[Path, str], catalog: Catalog, uid_map: dict[str, str]
) -> None:
    rendered = tmg.generate(tm.TWENTY_MODEL, catalog, uid_map)
    drifted = {**committed, tmg.ARTIFACT_PATH: committed[tmg.ARTIFACT_PATH].replace('"1"', '"2"', 1)}
    findings = tv.check_current(drifted, rendered)
    assert any(tmg.ARTIFACT_PATH.name in finding and "stale" in finding for finding in findings), findings


def test_a_missing_surface_is_named_stale(
    committed: dict[Path, str], catalog: Catalog, uid_map: dict[str, str]
) -> None:
    rendered = tmg.generate(tm.TWENTY_MODEL, catalog, uid_map)
    findings = tv.check_current({k: v for k, v in committed.items() if k != tmg.OPTIONS_PATH}, rendered)
    assert any(tmg.OPTIONS_PATH.name in finding for finding in findings), findings


# --- UID map -----------------------------------------------------------------------------------


def test_the_committed_uid_map_is_complete(catalog: Catalog, uid_map: dict[str, str]) -> None:
    assert tv.check_uid_map(uid_map, tm.TWENTY_MODEL, catalog) == ()


def test_a_missing_uid_is_reported_by_key(catalog: Catalog, uid_map: dict[str, str]) -> None:
    key = tm.uid_map_keys(tm.TWENTY_MODEL, catalog)[0]
    findings = tv.check_uid_map({k: v for k, v in uid_map.items() if k != key}, tm.TWENTY_MODEL, catalog)
    assert any(key in finding for finding in findings), findings


def test_an_orphan_uid_is_reported(catalog: Catalog, uid_map: dict[str, str]) -> None:
    orphan = {**uid_map, "patient.fieldNobodyDeclares": "6f0f1f7c-6f8f-4a0e-9a5f-2b1e2d3c4b5a"}
    assert any("fieldNobodyDeclares" in finding for finding in tv.check_uid_map(orphan, tm.TWENTY_MODEL, catalog))


def test_a_non_canonical_uid_value_is_reported(catalog: Catalog, uid_map: dict[str, str]) -> None:
    key = tm.uid_map_keys(tm.TWENTY_MODEL, catalog)[0]
    findings = tv.check_uid_map({**uid_map, key: "NOT-A-UUID"}, tm.TWENTY_MODEL, catalog)
    assert any(key in finding for finding in findings), findings


def test_a_reused_uid_value_is_reported(catalog: Catalog, uid_map: dict[str, str]) -> None:
    """Two keys sharing an identifier makes the second sync rename the first field, not create it."""
    first, second = tm.uid_map_keys(tm.TWENTY_MODEL, catalog)[:2]
    findings = tv.check_uid_map({**uid_map, second: uid_map[first]}, tm.TWENTY_MODEL, catalog)
    assert any(uid_map[first] in finding for finding in findings), findings


# --- Options against the catalog ---------------------------------------------------------------


def test_the_committed_options_match_the_catalog(artifact: dict[str, Any], catalog: Catalog) -> None:
    assert tv.check_options_against_catalog(artifact, tm.TWENTY_MODEL, catalog) == ()


def test_an_option_the_catalog_does_not_carry_is_reported(artifact: dict[str, Any], catalog: Catalog) -> None:
    broken = copy.deepcopy(artifact)
    operation = _field_op(broken, "patientProgram", "lifecycleStatus")
    operation["options"].append({
        "universalIdentifier": "9d3a0f10-1f2e-4f3a-8b4c-5d6e7f8a9b0c",
        "value": "invented",
        "label": "Invented",
        "position": len(operation["options"]) + 1,
    })
    findings = tv.check_options_against_catalog(broken, tm.TWENTY_MODEL, catalog)
    assert any("invented" in finding for finding in findings), findings


def test_a_dropped_catalog_state_is_reported(artifact: dict[str, Any], catalog: Catalog) -> None:
    broken = copy.deepcopy(artifact)
    operation = _field_op(broken, "patientProgram", "lifecycleStatus")
    dropped = operation["options"].pop()["value"]
    findings = tv.check_options_against_catalog(broken, tm.TWENTY_MODEL, catalog)
    assert any(dropped in finding for finding in findings), findings


def test_a_field_the_model_never_declares_is_reported(artifact: dict[str, Any], catalog: Catalog) -> None:
    broken = copy.deepcopy(artifact)
    _field_op(broken, "patientProgram", "lifecycleStatus")["name"] = "inventedStatus"
    findings = tv.check_options_against_catalog(broken, tm.TWENTY_MODEL, catalog)
    assert any("inventedStatus" in finding for finding in findings), findings


# --- TypeScript against the artifact -----------------------------------------------------------


def test_the_committed_typescript_matches_the_artifact(options_ts: str, artifact: dict[str, Any]) -> None:
    assert tv.check_options_ts_against_artifact(options_ts, artifact) == ()


def test_parsing_the_typescript_yields_the_committed_option_sets(options_ts: str) -> None:
    parsed = tv.parse_options_ts(options_ts)
    assert "patientProgram.lifecycleStatus" in parsed
    assert all(option.position >= 1 for options in parsed.values() for option in options)


def test_a_typescript_only_value_change_is_reported(options_ts: str, artifact: dict[str, Any]) -> None:
    drifted = options_ts.replace('value: "credentialed"', 'value: "recredentialed"', 1)
    assert drifted != options_ts, "fixture no longer contains the value it mutates"
    findings = tv.check_options_ts_against_artifact(drifted, artifact)
    assert any("provider.lifecycleStatus" in finding for finding in findings), findings


def test_a_typescript_only_identifier_change_is_reported(options_ts: str, artifact: dict[str, Any]) -> None:
    drifted = options_ts.replace(
        'universalIdentifier: "4ae15917-410c-4be0-8c31-aa22b1963487"',
        'universalIdentifier: "00000000-0000-4000-8000-000000000000"',
        1,
    )
    assert drifted != options_ts, "fixture no longer contains the identifier it mutates"
    assert tv.check_options_ts_against_artifact(drifted, artifact)


def test_a_field_missing_from_the_typescript_is_reported(options_ts: str, artifact: dict[str, Any]) -> None:
    drifted = options_ts.replace('  "provider.lifecycleStatus": PROVIDER_LIFECYCLE_STATUS_OPTIONS,\n', "", 1)
    assert drifted != options_ts, "fixture no longer contains the index entry it removes"
    findings = tv.check_options_ts_against_artifact(drifted, artifact)
    assert any("provider.lifecycleStatus" in finding for finding in findings), findings


def test_an_unparseable_options_file_is_a_finding_not_a_crash(artifact: dict[str, Any]) -> None:
    findings = tv.check_options_ts_against_artifact("export const OPTIONS_BY_FIELD = {\n", artifact)
    assert findings


def test_an_index_entry_pointing_at_no_constant_is_reported(options_ts: str, artifact: dict[str, Any]) -> None:
    drifted = options_ts.replace(
        '  "provider.lifecycleStatus": PROVIDER_LIFECYCLE_STATUS_OPTIONS,',
        '  "provider.lifecycleStatus": MISSING_OPTIONS,',
        1,
    )
    findings = tv.check_options_ts_against_artifact(drifted, artifact)
    assert any("MISSING_OPTIONS" in finding for finding in findings), findings


# --- CLI ---------------------------------------------------------------------------------------


def test_the_cli_reports_findings_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tv, "validate", lambda *_: ("artifact schema: invented finding",))
    assert tv.main([]) == 1
    assert "invented finding" in capsys.readouterr().out


def test_the_validator_opens_no_socket() -> None:
    """The whole module runs under disabled sockets; this states the contract it holds to."""
    source = Path(tv.__file__).read_text()
    for forbidden in ("httpx", "requests", "urllib", "socket", "twenty_deploy"):
        assert f"import {forbidden}" not in source, f"the validator imports {forbidden} — it reads files only"
