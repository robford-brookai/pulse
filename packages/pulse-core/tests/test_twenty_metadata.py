"""Generator tests (pulse-app-scaffold 2.2) — the three generated surfaces and their invariants.

The committed files *are* the golden files: `generate()` renders in memory and every output is
compared against what the tree carries, which is the same posture `catalog_gen`'s `--check` sets.
A golden that lives beside the artifact it verifies drifts with it; one that *is* the artifact
cannot.

Sockets are disabled for the whole module (`twenty-metadata-artifact` spec, "Generation is
offline"): every test here — including the full render — runs with no network available, so a
generator that grew a live-apply path would fail the suite rather than pass it quietly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from pulse_core import twenty_metadata as tmg
from pulse_core import twenty_model as tm
from pulse_core.catalog_gen import Catalog, load_catalog
from pulse_core.twenty_model import encode_option_value
from pytest_socket import disable_socket, enable_socket

_ENTITY_OBJECTS = ("patient", "program", "patientProgram", "provider", "clinic")


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
def rendered(catalog: Catalog, uid_map: dict[str, str]) -> dict[Path, str]:
    return tmg.generate(tm.TWENTY_MODEL, catalog, uid_map)


@pytest.fixture(scope="module")
def artifact(rendered: dict[Path, str]) -> dict:
    loaded: dict = json.loads(rendered[tmg.ARTIFACT_PATH])
    return loaded


def _role(artifact: dict, name: str) -> dict:
    roles = [op for op in artifact["operations"] if op["operation"] == "createRole" and op["name"] == name]
    assert len(roles) == 1, f"expected exactly one {name!r} role operation, found {len(roles)}"
    return roles[0]


def _object_permission(role: dict, object_name: str) -> dict | None:
    return next((p for p in role["objectPermissions"] if p["objectNameSingular"] == object_name), None)


def _field_permission(role: dict, object_name: str, field_name: str) -> dict | None:
    return next(
        (
            p
            for p in role["fieldPermissions"]
            if p["objectNameSingular"] == object_name and p["fieldName"] == field_name
        ),
        None,
    )


def _fields(artifact: dict) -> list[dict]:
    return [op for op in artifact["operations"] if op["operation"] == "createField"]


# --- 1. Golden files and determinism ---------------------------------------------------------


def test_the_committed_surfaces_match_a_fresh_render(rendered: dict[Path, str]) -> None:
    """The golden test for all three outputs: the tree equals what the generator produces."""
    stale = sorted(path.name for path, text in rendered.items() if path.read_text() != text)
    assert stale == [], f"stale generated surfaces {stale} — run: task twenty:gen"


def test_the_generator_writes_exactly_three_surfaces(rendered: dict[Path, str]) -> None:
    assert sorted(path.name for path in rendered) == ["operations.json", "options.ts", "projection-lookup.ts"]


def test_re_render_is_byte_identical(catalog: Catalog, uid_map: dict[str, str]) -> None:
    first = tmg.generate(tm.TWENTY_MODEL, catalog, uid_map)
    second = tmg.generate(tm.TWENTY_MODEL, catalog, uid_map)
    assert first == second


def test_check_mode_passes_on_the_committed_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert tmg.main(["--check"]) == 0
    assert "stale" not in capsys.readouterr().out


def test_check_mode_fails_naming_a_drifted_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The staleness signal task 2.3 wires into `check` — a drifted artifact is named, not summarized."""
    drifted = tmp_path / "operations.json"
    drifted.write_text('{"artifactVersion": "0"}\n')
    monkeypatch.setattr(tmg, "ARTIFACT_PATH", drifted)
    assert tmg.main(["--check"]) == 1
    assert "operations.json" in capsys.readouterr().out


def test_writing_the_surfaces_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for attribute, name in (
        ("OPTIONS_PATH", "options.ts"),
        ("PROJECTION_LOOKUP_PATH", "projection-lookup.ts"),
        ("ARTIFACT_PATH", "operations.json"),
    ):
        monkeypatch.setattr(tmg, attribute, tmp_path / name)
    assert tmg.main([]) == 0
    written = {path.name: path.read_text() for path in tmp_path.iterdir()}
    assert tmg.main([]) == 0
    assert {path.name: path.read_text() for path in tmp_path.iterdir()} == written


# --- 2. One run, one vocabulary --------------------------------------------------------------


def test_a_catalog_state_becomes_a_select_option_everywhere_at_once(
    rendered: dict[Path, str], artifact: dict, catalog: Catalog
) -> None:
    """The spec scenario, over every state of every dimension the model carries — not a sample."""
    options_ts = rendered[tmg.OPTIONS_PATH]
    lookup_ts = rendered[tmg.PROJECTION_LOOKUP_PATH]
    checked = 0
    for row in tmg.projection_rows(tm.TWENTY_MODEL, catalog):
        picklist = next(
            op
            for op in _fields(artifact)
            if op["objectNameSingular"] == row.object_name and op["name"] == row.status_field
        )
        assert row.value in [option["value"] for option in picklist["options"]]
        assert f'value: "{row.value}"' in options_ts
        assert f'"{row.event_type}"' in lookup_ts
        # The same state also reaches the event-type registry: one catalog, one vocabulary.
        event_type_options = next(op for op in _fields(artifact) if op["name"] == "eventType")
        assert row.event_type in [option["value"] for option in event_type_options["options"]]
        checked += 1
    assert checked == sum(len(catalog.subjects[subject].transitions) for subject in ("enrollment", "billing_episode"))


def test_every_dimension_bound_option_set_equals_the_catalog_subject(artifact: dict, catalog: Catalog) -> None:
    seen = 0
    for obj in tm.TWENTY_MODEL.objects:
        for field in obj.fields:
            if field.option_source != "catalog_subject":
                continue
            assert field.dimension is not None
            operation = next(
                op
                for op in _fields(artifact)
                if op["objectNameSingular"] == obj.name_singular and op["name"] == field.name
            )
            assert [option["value"] for option in operation["options"]] == sorted(
                catalog.subjects[field.dimension].transitions
            )
            seen += 1
    assert seen == 2


def test_the_typescript_options_equal_the_artifact_options(rendered: dict[Path, str], artifact: dict) -> None:
    """Decision 5's cross-check, asserted here so task 2.3's validator has a proven property."""
    from_ts = _parse_options_ts(rendered[tmg.OPTIONS_PATH])
    from_artifact = {
        f"{op['objectNameSingular']}.{op['name']}": [(o["value"], o["universalIdentifier"]) for o in op["options"]]
        for op in _fields(artifact)
        if op.get("options")
    }
    assert from_ts == from_artifact


def test_every_generated_option_carries_the_encoding_the_live_server_stores(rendered: dict[Path, str]) -> None:
    """Task 6.6: `encodedValue` is the deploy boundary's own result, emitted beside `value`.

    The artifact keeps the catalog vocabulary and `twenty_deploy` encodes at the wire; anything
    keyed on a *stored* value — a kanban column's `fieldValue` above all — needs the encoded form.
    Demo3's assertion 3 found the live board keyed on `value`, a board no card could reach.
    """
    pairs = re.findall(r'value: "(.+?)", encodedValue: "(.+?)"', rendered[tmg.OPTIONS_PATH])
    assert pairs, "generated/options.ts emits no encodedValue"
    assert [(value, encoded) for value, encoded in pairs if encoded != encode_option_value(value)] == []


def _parse_options_ts(source: str) -> dict[str, list[tuple[str, str]]]:
    """Read the generated TypeScript as data — the same trick task 2.3's validator needs."""
    parsed: dict[str, list[tuple[str, str]]] = {}
    key: str | None = None
    for line in source.splitlines():
        heading = re.match(r"^// (\S+)$", line)
        if heading:
            key = heading.group(1)
            parsed[key] = []
        entry = re.search(
            r'value: "(.+?)", encodedValue: ".*?", label: ".*?", position: \d+, universalIdentifier: "(.+?)"', line
        )
        if entry and key is not None:
            parsed[key].append((entry.group(1), entry.group(2)))
    return parsed


def test_the_projection_lookup_covers_every_dimension_bound_state(rendered: dict[Path, str], catalog: Catalog) -> None:
    lookup = rendered[tmg.PROJECTION_LOOKUP_PATH]
    rows = tmg.projection_rows(tm.TWENTY_MODEL, catalog)
    assert [row.event_type for row in rows] == sorted({row.event_type for row in rows}), "lookup rows are not sorted"
    for row in rows:
        assert f'"{row.event_type}": {{ objectNameSingular: "{row.object_name}"' in lookup
        assert row.as_of_field == f"{row.status_field}AsOf"


def test_literal_status_fields_stay_out_of_the_lookup(catalog: Catalog) -> None:
    """Provider/clinic lifecycle is model-literal at v1: no catalog dimension, so no lookup row.

    A generated row for `contract.active` would assert a provider grain nobody ratified (task 2.1's
    HANDOFF note). Those events stay lookup misses — no-ops the handler already tolerates.
    """
    targets = {row.object_name for row in tmg.projection_rows(tm.TWENTY_MODEL, catalog)}
    assert targets == {"patientProgram"}


# --- 3. universalIdentifiers are read, never minted -------------------------------------------


def test_a_missing_uid_is_a_generation_error_naming_the_key(catalog: Catalog, uid_map: dict[str, str]) -> None:
    before = tm.UID_MAP_PATH.read_text()
    incomplete = {key: value for key, value in uid_map.items() if key != "patientProgram.lifecycleStatus.active"}
    with pytest.raises(KeyError, match=re.escape("patientProgram.lifecycleStatus.active")):
        tmg.generate(tm.TWENTY_MODEL, catalog, incomplete)
    assert tm.UID_MAP_PATH.read_text() == before, "the generator wrote to the UID map"


def test_a_missing_object_uid_is_a_generation_error(catalog: Catalog, uid_map: dict[str, str]) -> None:
    incomplete = {key: value for key, value in uid_map.items() if key != "domainEvent"}
    with pytest.raises(KeyError, match="domainEvent"):
        tmg.generate(tm.TWENTY_MODEL, catalog, incomplete)


def test_every_emitted_identifier_comes_from_the_map(artifact: dict, uid_map: dict[str, str]) -> None:
    emitted = set(re.findall(r'"universalIdentifier": "(.+?)"', json.dumps(artifact)))
    assert emitted <= set(uid_map.values())
    assert emitted, "the artifact carries no identifiers at all"


# --- 4. Single-writer roles -------------------------------------------------------------------


def test_staff_cannot_write_a_status_field(artifact: dict) -> None:
    """The spec scenario: read without write on every status field, read-only DomainEvent."""
    staff = _role(artifact, "staff")
    status = tmg.status_fields(tm.TWENTY_MODEL)
    assert status, "the model declares no status fields — the assertion below would be vacuous"
    for entry in status:
        for field_name in (entry.status_field, entry.as_of_field):
            permission = _field_permission(staff, entry.object_name, field_name)
            assert permission is not None, f"staff has no field permission for {entry.object_name}.{field_name}"
            assert permission["canRead"] is True
            assert permission["canUpdate"] is False

    domain_event = _object_permission(staff, "domainEvent")
    assert domain_event is not None
    assert domain_event["canRead"] is True
    assert (domain_event["canCreate"], domain_event["canUpdate"], domain_event["canDelete"]) == (False, False, False)


def test_staff_can_write_the_entity_objects_it_owns(artifact: dict) -> None:
    staff = _role(artifact, "staff")
    for object_name in _ENTITY_OBJECTS:
        permission = _object_permission(staff, object_name)
        assert permission is not None
        assert permission["canRead"] is True
        assert permission["canUpdate"] is True


def test_producers_hold_create_only_on_domain_event(artifact: dict) -> None:
    producer = _role(artifact, "producer")
    assert [p["objectNameSingular"] for p in producer["objectPermissions"]] == ["domainEvent"]
    permission = _object_permission(producer, "domainEvent")
    assert permission is not None
    assert permission["canCreate"] is True
    assert (permission["canRead"], permission["canUpdate"], permission["canDelete"]) == (False, False, False)


def test_the_app_role_writes_only_what_the_projection_needs(artifact: dict) -> None:
    app = _role(artifact, "app")
    domain_event = _object_permission(app, "domainEvent")
    assert domain_event is not None
    assert domain_event["canDelete"] is False
    writable = {
        p["fieldName"]
        for p in app["fieldPermissions"]
        if p["objectNameSingular"] == "domainEvent" and p["canUpdate"] is True
    }
    assert writable == set()
    unwritable = {
        p["fieldName"]
        for p in app["fieldPermissions"]
        if p["objectNameSingular"] == "domainEvent" and p["canUpdate"] is False
    }
    # Everything except the three relation fields the handler binds is read-only for the app.
    assert "eventType" in unwritable
    assert unwritable.isdisjoint({"patientProgram", "provider", "clinic"})


def test_no_role_can_delete_a_domain_event(artifact: dict) -> None:
    """The immutability policy, asserted across every role the artifact declares."""
    for operation in artifact["operations"]:
        if operation["operation"] != "createRole":
            continue
        permission = _object_permission(operation, "domainEvent")
        if permission is not None:
            assert permission["canDelete"] is False, f"role {operation['name']} can delete DomainEvent"


# --- 5. Artifact shape ------------------------------------------------------------------------


def test_the_artifact_declares_its_provenance(artifact: dict, catalog: Catalog) -> None:
    assert artifact["artifactVersion"] == tmg.ARTIFACT_VERSION
    assert artifact["catalogVersion"] == catalog.catalog_version
    assert artifact["generator"] == "pulse_core.twenty_metadata"


def test_objects_are_created_before_the_fields_that_hang_off_them(artifact: dict) -> None:
    """The provisioning order twenty-data-model.md names: objects → fields → relations → roles."""
    kinds = [operation["operation"] for operation in artifact["operations"]]
    order = ["createObject", "createField", "createRelation", "createRole"]
    assert kinds == sorted(kinds, key=order.index)


def test_every_model_object_and_field_reaches_the_artifact(artifact: dict) -> None:
    objects = {op["nameSingular"] for op in artifact["operations"] if op["operation"] == "createObject"}
    assert objects == {obj.name_singular for obj in tm.TWENTY_MODEL.objects}

    emitted = {(op["objectNameSingular"], op["name"]) for op in _fields(artifact)}
    emitted |= {
        (op["from"]["objectNameSingular"], op["from"]["fieldName"])
        for op in artifact["operations"]
        if op["operation"] == "createRelation"
    }
    emitted |= {
        (op["to"]["objectNameSingular"], op["to"]["fieldName"])
        for op in artifact["operations"]
        if op["operation"] == "createRelation"
    }
    declared = {(obj.name_singular, field.name) for obj in tm.TWENTY_MODEL.objects for field in obj.fields}
    assert emitted == declared


def test_each_relation_is_emitted_once_from_its_many_side(artifact: dict) -> None:
    relations = [op for op in artifact["operations"] if op["operation"] == "createRelation"]
    assert {op["type"] for op in relations} == {"MANY_TO_ONE"}
    assert len(relations) == 5, "one operation per relation pair, not one per side"


def test_not_null_fields_carry_a_default(artifact: dict) -> None:
    """Scaffold-doc correction 3, carried into the artifact rather than left in the model."""
    for operation in _fields(artifact):
        if operation["isNullable"] is False:
            assert operation.get("defaultValue"), f"{operation['name']} is NOT NULL with no default"


# --- 6. Generation is offline -----------------------------------------------------------------


def test_the_generator_imports_no_network_client() -> None:
    """ "The generator never applies": the module has no transport to apply anything with."""
    source = Path(tmg.__file__).read_text()
    for forbidden in ("httpx", "requests", "urllib", "socket", "twenty_deploy"):
        assert f"import {forbidden}" not in source, f"the generator imports {forbidden}"
