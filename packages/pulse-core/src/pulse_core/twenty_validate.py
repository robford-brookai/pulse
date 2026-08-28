"""Committed-artifact validation (pulse-app-scaffold 2.3) — the CI half of the generator.

`twenty_metadata` renders; this module checks that what the tree carries is what the inputs say
it should carry, and that the artifact the deploy step will apply is well formed. It is what
`task check` runs (`task twenty:validate`), so it is Python-only by construction: the
TypeScript options surface is compared by *parsing it as data*, never by shelling out to node —
CI has no node step yet, and a check that needs one is red CI (`docs/ci-lessons.md`).

Five checks, each independently callable so a test can break exactly one input:

- `check_schema` — the operation set parses against the shape the deploy step will read. Unknown
  keys are rejected (`extra="forbid"`): a key nobody reads is a silent no-op in production.
- `check_current` — every committed surface is byte-identical to a fresh render. This is the
  staleness gate: a drifted committed artifact fails CI, naming the file.
- `check_uid_map` — the map covers exactly the keys the model asks for, every value is a
  canonical UUID, and no two keys share one.
- `check_options_against_catalog` — each catalog-bound SELECT's options in the artifact equal
  the catalog's states for that dimension, in order.
- `check_options_ts_against_artifact` — the generated TypeScript and the artifact carry
  identical option sets, so the app's compile-time vocabulary and the deployed picklist cannot
  diverge.

Validation reads files and nothing else — no socket, and no path that talks to a Twenty
instance (that is `twenty_deploy`'s job, from the reviewed artifact).

Run: uv run python -m pulse_core.twenty_validate        (task twenty:validate)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from pulse_core.catalog_gen import Catalog, load_catalog
from pulse_core.twenty_metadata import ARTIFACT_PATH, OPTIONS_PATH, PROJECTION_LOOKUP_PATH, generate
from pulse_core.twenty_model import (
    TWENTY_MODEL,
    ModelDefinition,
    encode_option_value,
    is_well_formed_uuid,
    load_uid_map,
    resolve_options,
    uid_map_diff,
)

# `encode_option_value` was defined here until task 6.6 moved it down to `twenty_model` so that
# `twenty_metadata` could emit the encoded form into `generated/options.ts` without an import
# cycle. It is imported rather than re-defined, and stays importable from this module: every
# caller — `twenty_deploy`, `twenty_seed`, the ledger's Twenty mapping, the demos — reads it from
# here, where the deploy-boundary reasoning lives.

#: Every surface the validator reads from the tree, in the order findings are reported.
COMMITTED_PATHS = (OPTIONS_PATH, PROJECTION_LOOKUP_PATH, ARTIFACT_PATH)

#: The checks `validate` runs. Named so a test can assert none is orphaned — a validator nobody
#: calls gates nothing, which is the failure mode this whole module exists to prevent.
CHECK_NAMES = (
    "schema",
    "current",
    "uid_map",
    "options_against_catalog",
    "options_ts_against_artifact",
    "option_encoding_bijective",
)

Findings = tuple[str, ...]


# --- Operation-set schema ----------------------------------------------------------------------


def _canonical_uuid(value: str) -> str:
    if not is_well_formed_uuid(value):
        msg = "not a canonical lowercase UUID string"
        raise ValueError(msg)
    return value


Uid = Annotated[str, AfterValidator(_canonical_uuid)]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Option(_Strict):
    universalIdentifier: Uid
    value: str
    label: str
    position: int = Field(ge=1)


class _CreateObject(_Strict):
    operation: Literal["createObject"]
    universalIdentifier: Uid
    nameSingular: str
    namePlural: str
    labelSingular: str
    labelPlural: str
    icon: str
    description: str


class _CreateField(_Strict):
    operation: Literal["createField"]
    universalIdentifier: Uid
    objectNameSingular: str
    name: str
    type: Literal["TEXT", "FULL_NAME", "NUMBER", "DATE_TIME", "RAW_JSON", "SELECT"]
    label: str
    isNullable: bool
    isUnique: bool
    description: str | None = None
    defaultValue: str | None = None
    options: tuple[_Option, ...] = ()


class _RelationEnd(_Strict):
    universalIdentifier: Uid
    objectNameSingular: str
    fieldName: str
    label: str
    isNullable: bool | None = None


class _CreateRelation(_Strict):
    operation: Literal["createRelation"]
    type: Literal["MANY_TO_ONE", "ONE_TO_MANY"]
    from_: _RelationEnd = Field(alias="from")
    to: _RelationEnd


class _ObjectPermission(_Strict):
    objectNameSingular: str
    canRead: bool
    canCreate: bool
    canUpdate: bool
    canDelete: bool


class _FieldPermission(_Strict):
    objectNameSingular: str
    fieldName: str
    canRead: bool
    canUpdate: bool


class _CreateRole(_Strict):
    operation: Literal["createRole"]
    name: str
    label: str
    description: str
    objectPermissions: tuple[_ObjectPermission, ...]
    fieldPermissions: tuple[_FieldPermission, ...]


_Operation = Annotated[
    _CreateObject | _CreateField | _CreateRelation | _CreateRole,
    Field(discriminator="operation"),
]


class OperationSet(_Strict):
    """The artifact's shape. Adding a key here is a deliberate `ARTIFACT_VERSION` bump."""

    artifactVersion: str
    catalogVersion: str
    generator: str
    operations: tuple[_Operation, ...]


def check_schema(artifact: Any) -> Findings:
    """The operation set parses, with every operation a known kind carrying only known keys."""
    try:
        OperationSet.model_validate(artifact)
    except ValidationError as error:
        return tuple(
            f"artifact schema: {'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        )
    return ()


# --- Staleness ---------------------------------------------------------------------------------


def read_committed(paths: tuple[Path, ...] = COMMITTED_PATHS) -> dict[Path, str]:
    """The generated surfaces as the tree carries them. A missing file is absent, not an error."""
    return {path: path.read_text() for path in paths if path.exists()}


def check_current(committed: dict[Path, str], rendered: dict[Path, str]) -> Findings:
    """Every rendered surface matches the committed one byte for byte."""
    findings = [
        f"{path} is stale — the committed file is not what the inputs render; run: task twenty:gen"
        for path, text in sorted(rendered.items())
        if committed.get(path) != text
    ]
    return tuple(findings)


# --- UID map -----------------------------------------------------------------------------------


def check_uid_map(uid_map: dict[str, str], model: ModelDefinition, catalog: Catalog) -> Findings:
    """The map covers the model's keys exactly, with canonical values and no reuse."""
    missing, orphan = uid_map_diff(uid_map, model, catalog)
    findings = [f"uid map: missing universalIdentifier for {key!r}" for key in missing]
    findings.extend(f"uid map: orphan universalIdentifier {key!r} — the model never asks for it" for key in orphan)
    findings.extend(
        f"uid map: value for {key!r} is not a canonical UUID string: {value!r}"
        for key, value in sorted(uid_map.items())
        if not is_well_formed_uuid(value)
    )
    by_value: dict[str, list[str]] = {}
    for key, value in sorted(uid_map.items()):
        by_value.setdefault(value, []).append(key)
    findings.extend(
        f"uid map: {value} is shared by {keys} — one identifier names one thing"
        for value, keys in sorted(by_value.items())
        if len(keys) > 1
    )
    return tuple(findings)


# --- Options against the catalog ---------------------------------------------------------------


def _artifact_field_options(artifact: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """`<object>.<field>` -> the option values the artifact carries, in position order."""
    return {
        f"{operation['objectNameSingular']}.{operation['name']}": tuple(
            option["value"] for option in operation.get("options", ())
        )
        for operation in artifact.get("operations", ())
        if operation.get("operation") == "createField" and operation.get("options")
    }


def check_options_against_catalog(artifact: dict[str, Any], model: ModelDefinition, catalog: Catalog) -> Findings:
    """Each artifact option set equals what the model's option source resolves to in this catalog.

    Equality rather than containment: a dimension whose states the artifact merely *subsets* is a
    field that silently cannot represent a state the ledger already emits.
    """
    findings: list[str] = []
    for key, values in sorted(_artifact_field_options(artifact).items()):
        object_name, _, field_name = key.partition(".")
        obj = model.object(object_name)
        field = obj.field(field_name) if obj is not None else None
        if field is None:
            findings.append(f"options: {key} carries options for a field the model never declares")
            continue
        expected = tuple(option.value for option in resolve_options(field, catalog))
        if values != expected:
            extra = sorted(set(values) - set(expected))
            absent = sorted(set(expected) - set(values))
            findings.append(
                f"options: {key} does not match its source (extra: {extra}, missing: {absent})"
                if extra or absent
                else f"options: {key} matches its source but in a different order"
            )
    return tuple(findings)


def check_option_encoding(artifact: dict[str, Any]) -> Findings:
    """No two option values of one field collide once encoded for the live server.

    A collision would make two catalog states indistinguishable on the target — the deploy
    would apply, and the ledger would silently lose a distinction. Refused here, before any
    operation is planned.
    """
    findings: list[str] = []
    for key, values in sorted(_artifact_field_options(artifact).items()):
        by_encoded: dict[str, list[str]] = {}
        for value in values:
            by_encoded.setdefault(encode_option_value(value), []).append(value)
        findings.extend(
            f"option encoding: {key} values {sorted(originals)} collide as {encoded!r} on the live server"
            for encoded, originals in sorted(by_encoded.items())
            if len(originals) > 1
        )
    return tuple(findings)


# --- TypeScript against the artifact -----------------------------------------------------------

_CONST_START = re.compile(r"^export const (?P<const>\w+): GeneratedOption\[\] = \[$")
_OPTION_LINE = re.compile(
    r'^\s*\{ value: "(?P<value>[^"]*)", encodedValue: "(?P<encoded>[^"]*)", '
    r'label: "(?P<label>[^"]*)", '
    r'position: (?P<position>\d+), universalIdentifier: "(?P<uid>[^"]*)", '
    r'id: "(?P<id>[^"]*)", color: "(?P<color>[^"]*)" \},$'
)
_INDEX_START = re.compile(r"^export const OPTIONS_BY_FIELD")
_INDEX_LINE = re.compile(r'^\s*"(?P<key>[^"]+)": (?P<const>\w+),$')


class TsOption(_Strict):
    """One option as the generated TypeScript declares it, read as data rather than executed."""

    value: str
    encodedValue: str
    label: str
    position: int
    universalIdentifier: Uid


def _parse_option_constants(text: str) -> dict[str, tuple[TsOption, ...]]:
    """Every `export const X: readonly GeneratedOption[]` block, by constant name.

    The file is generated by this repo with one option per line, so a line parser is exact for
    every input it will ever see; a line inside a block that it cannot read is a `ValueError` the
    caller turns into a finding, never a silent empty result.
    """
    constants: dict[str, tuple[TsOption, ...]] = {}
    current: str | None = None
    options: list[TsOption] = []
    for line in text.splitlines():
        if (start := _CONST_START.match(line)) is not None:
            current, options = start["const"], []
        elif current is None:
            continue
        elif line.startswith("]"):
            constants[current] = tuple(options)
            current = None
        elif (option := _OPTION_LINE.match(line)) is not None:
            options.append(
                TsOption(
                    value=option["value"],
                    encodedValue=option["encoded"],
                    label=option["label"],
                    position=int(option["position"]),
                    universalIdentifier=option["uid"],
                )
            )
        else:
            msg = f"unparseable option line in {OPTIONS_PATH.name}: {line!r}"
            raise ValueError(msg)
    return constants


def _parse_index(text: str) -> dict[str, str]:
    """The `OPTIONS_BY_FIELD` map: `<object>.<field>` -> the constant it points at."""
    index: dict[str, str] = {}
    in_index = False
    for line in text.splitlines():
        if _INDEX_START.match(line):
            in_index = True
        elif in_index and line.startswith("}"):
            break
        elif in_index and (entry := _INDEX_LINE.match(line)) is not None:
            index[entry["key"]] = entry["const"]
    if not index:
        msg = f"{OPTIONS_PATH.name} declares no OPTIONS_BY_FIELD index"
        raise ValueError(msg)
    return index


def parse_options_ts(text: str) -> dict[str, tuple[TsOption, ...]]:
    """`<object>.<field>` -> its options, read out of `generated/options.ts` without node.

    An index entry naming a constant the file does not declare yields an empty option set here
    and a finding from `_index_gaps` — the two together say both what is wrong and where.
    """
    constants = _parse_option_constants(text)
    return {key: constants.get(const, ()) for key, const in sorted(_parse_index(text).items())}


def check_options_ts_against_artifact(options_ts: str, artifact: dict[str, Any]) -> Findings:
    """The TypeScript option surface and the artifact declare identical option sets."""
    try:
        parsed = parse_options_ts(options_ts)
        index_gaps = _index_gaps(options_ts)
    except (ValueError, ValidationError) as error:
        return (f"options.ts: {error}",)

    findings = list(index_gaps)
    artifact_options = {
        f"{operation['objectNameSingular']}.{operation['name']}": tuple(
            (option["value"], option["label"], option["position"], option["universalIdentifier"])
            for option in operation.get("options", ())
        )
        for operation in artifact.get("operations", ())
        if operation.get("operation") == "createField" and operation.get("options")
    }
    ts_options = {
        key: tuple((o.value, o.label, o.position, o.universalIdentifier) for o in options)
        for key, options in parsed.items()
    }
    for key in sorted(set(artifact_options) | set(ts_options)):
        if key not in ts_options:
            findings.append(f"options.ts: {key} is in the artifact but not in the generated TypeScript")
        elif key not in artifact_options:
            findings.append(f"options.ts: {key} is in the generated TypeScript but not in the artifact")
        elif ts_options[key] != artifact_options[key]:
            findings.append(f"options.ts: {key} option set differs from the artifact's")
    # `encodedValue` is what a kanban column keys on, so a wrong one is a board whose cards can
    # never land (demo3 assertion 3). The artifact carries the catalog vocabulary, so this is
    # checked against the encoding function rather than against the artifact.
    findings.extend(
        f"options.ts: {key} option {option.value!r} carries encodedValue "
        f"{option.encodedValue!r}, not {encode_option_value(option.value)!r}"
        for key, options in sorted(parsed.items())
        for option in options
        if option.encodedValue != encode_option_value(option.value)
    )
    return tuple(findings)


def _index_gaps(options_ts: str) -> Findings:
    """Index entries naming a constant the file does not declare — a TS-only compile error."""
    declared = {match["const"] for line in options_ts.splitlines() if (match := _CONST_START.match(line))}
    named = {
        match["const"]
        for line in options_ts.splitlines()
        if (match := _INDEX_LINE.match(line)) and match["const"] not in declared
    }
    return tuple(f"options.ts: OPTIONS_BY_FIELD names undeclared constant {const}" for const in sorted(named))


# --- Aggregate ---------------------------------------------------------------------------------


def validate_verbose(model: ModelDefinition, catalog: Catalog, uid_map: dict[str, str]) -> dict[str, Findings]:
    """Every check, keyed by name — the aggregate a test can assert is complete."""
    committed = read_committed()
    artifact_text = committed.get(ARTIFACT_PATH)
    try:
        artifact: dict[str, Any] = json.loads(artifact_text) if artifact_text is not None else {}
    except json.JSONDecodeError as error:
        artifact = {}
        parse_failure: Findings = (f"{ARTIFACT_PATH.name} is not valid JSON: {error}",)
    else:
        parse_failure = () if artifact_text is not None else (f"{ARTIFACT_PATH} is missing",)
    return {
        "schema": parse_failure + (check_schema(artifact) if not parse_failure else ()),
        "current": check_current(committed, generate(model, catalog, uid_map)),
        "uid_map": check_uid_map(uid_map, model, catalog),
        "options_against_catalog": check_options_against_catalog(artifact, model, catalog),
        "options_ts_against_artifact": check_options_ts_against_artifact(committed.get(OPTIONS_PATH, ""), artifact),
        "option_encoding_bijective": check_option_encoding(artifact),
    }


def validate(model: ModelDefinition, catalog: Catalog, uid_map: dict[str, str]) -> Findings:
    """Every finding across every check, in `CHECK_NAMES` order."""
    results = validate_verbose(model, catalog, uid_map)
    return tuple(finding for name in CHECK_NAMES for finding in results[name])


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: print every finding, exit 1 if there is one."""
    parser = argparse.ArgumentParser(description="Validate the committed Twenty metadata artifact and surfaces.")
    parser.parse_args(argv)

    catalog = load_catalog()
    findings = validate(TWENTY_MODEL, catalog, load_uid_map())
    for finding in findings:
        print(finding)
    if findings:
        print(f"{len(findings)} problem(s) — the committed Twenty artifact is not valid")
        return 1
    print(f"artifact valid against catalog {catalog.catalog_version}: {', '.join(CHECK_NAMES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
