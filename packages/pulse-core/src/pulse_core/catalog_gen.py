"""Catalog → command-surface generator (pulse-ledger-core design decision 4).

Reads the authoritative state catalog (`catalog/state_catalog.yaml`, repo root) as its only
input and emits `pulse_core/generated/__init__.py`: transition tables, the trinary verdict
enum, and one Pydantic command model per catalog command. The generated module is committed and
version-pinned to `catalog_version`; producers and the write-path validator both import it.

The catalog loads through `load_catalog` into the `Catalog` model — the state-bearing subjects
with their transition adjacency, the command vocabulary, the reason ValueSets, program config,
and a semver `catalog_version`.

Regenerate:        uv run python -m pulse_core.catalog_gen
Verify (no write): uv run python -m pulse_core.catalog_gen --check
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldType = Literal["str", "optional_str", "datetime", "date", "verdict_outcome", "json"]

_FIELD_ANNOTATIONS: dict[str, str] = {
    "str": "str",
    "optional_str": "str | None = None",
    "datetime": "datetime",
    "date": "date",
    "verdict_outcome": "VerdictOutcome",
    "json": "dict[str, object] | None = None",
}

PACKAGE_ROOT = Path(__file__).parent
GENERATED_PATH = PACKAGE_ROOT / "generated" / "__init__.py"
# The authoritative catalog is a repo-level artifact, not a package resource (design decision 1):
# four generated surfaces derive from it, and regeneration is a dev/CI-time command reading the
# repo tree. Only the committed generated module ships in the wheel.
REPO_ROOT = PACKAGE_ROOT.parents[3]
CATALOG_PATH = REPO_ROOT / "catalog" / "state_catalog.yaml"

# MAJOR.MINOR.PATCH, no leading zeros, no pre-release or build metadata (design decision 3).
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class SubjectSpec(BaseModel):
    """One state-bearing subject: who owns its machine and the adjacency as drawn in §5.2."""

    model_config = ConfigDict(extra="forbid")

    ownership: Literal["ledger", "recorded"]
    transitions: dict[str, list[str]]

    @model_validator(mode="after")
    def _targets_are_declared_states(self) -> SubjectSpec:
        states = set(self.transitions)
        for state, targets in self.transitions.items():
            unknown = sorted(set(targets) - states)
            if unknown:
                msg = f"transition {state!r} -> {unknown} targets states missing from the machine"
                raise ValueError(msg)
        return self


class CommandSpec(BaseModel):
    """One command type: optional pinned subject, backfill restriction, payload fields."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str | None = None
    backfill_only: bool = False
    fields: dict[str, FieldType] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _verdict_fields_pair_with_a_reason(self) -> CommandSpec:
        has_verdict = any(kind == "verdict_outcome" for kind in self.fields.values())
        if has_verdict and self.fields.get("reason") != "optional_str":
            msg = "a verdict_outcome field requires a companion `reason: optional_str` field"
            raise ValueError(msg)
        return self


class ValueSetSpec(BaseModel):
    """One reason ValueSet: codes are the keys, so a code appears once and order is not meaning."""

    model_config = ConfigDict(extra="forbid")

    description: str
    codes: dict[str, str] = Field(min_length=1)


class ProgramSpec(BaseModel):
    """One program's configuration (I6: programs are configuration, not schema)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    # The gate `pending_start -> active` must clear (§5.2), and the CMS exclusivity group the
    # command API enforces against concurrent enrollments (I6). Both are optional because the
    # design records them for some programs only; a later catalog PR fills the gaps.
    entry_gate: str | None = None
    exclusivity_group: str | None = None


class CatalogCommandSpec(CommandSpec):
    """A command, plus the optional ValueSet its `reason` binds to (§5.2 reason CodeableConcept)."""

    reason_valueset: str | None = None


class Catalog(BaseModel):
    """The authoritative state catalog: subjects, commands, ValueSets, programs, and semver.

    The subject and command specs carry over the retired Appendix C seed's schema unchanged,
    extended where v1 adds a section (`reason_valueset`, `valuesets`, `programs`,
    `registry_subjects`).
    """

    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    subjects: dict[str, SubjectSpec]
    commands: dict[str, CatalogCommandSpec]
    valuesets: dict[str, ValueSetSpec]
    programs: dict[str, ProgramSpec]
    # Subjects a command can be pinned to that carry no state machine — the registry anchors
    # (Person, Provider, Clinic). They are not in `subjects`, which is the state surface the
    # generator emits adjacency for.
    registry_subjects: list[str] = Field(default_factory=list)

    # A field validator, not a model one: it must still report when another section is also
    # malformed, so a rejected catalog names every violation at once.
    @field_validator("catalog_version")
    @classmethod
    def _version_is_semver(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            msg = f"catalog_version {value!r} is not a MAJOR.MINOR.PATCH semver"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _command_references_are_declared(self) -> Catalog:
        declared_subjects = set(self.subjects) | set(self.registry_subjects)
        for command, spec in self.commands.items():
            if spec.subject_type is not None and spec.subject_type not in declared_subjects:
                msg = f"command {command!r} pins undeclared subject {spec.subject_type!r}"
                raise ValueError(msg)
            if spec.reason_valueset is not None and spec.reason_valueset not in self.valuesets:
                msg = f"command {command!r} binds undeclared ValueSet {spec.reason_valueset!r}"
                raise ValueError(msg)
        return self


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    """Load and validate the authoritative catalog; a malformed file raises and yields nothing."""
    with path.open() as fh:
        return Catalog.model_validate(yaml.safe_load(fh))


def _class_name(command_type: str) -> str:
    return "".join(part.capitalize() for part in command_type.split("_")) + "Command"


def _render_header(catalog: Catalog) -> list[str]:
    return [
        '"""Generated command surface — DO NOT EDIT.',
        "",
        "Generated by `pulse_core.catalog_gen` from `catalog/state_catalog.yaml`",
        f"(catalog_version: {catalog.catalog_version}). Regenerate with:",
        "",
        "    uv run python -m pulse_core.catalog_gen",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping",
        "from datetime import date, datetime",
        "from enum import Enum",
        "from typing import Annotated, Literal, TypeAlias",
        "",
        "from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator",
        "",
        f'CATALOG_VERSION = "{catalog.catalog_version}"',
    ]


def _render_transitions(catalog: Catalog) -> list[str]:
    lines = ["TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {"]
    for subject in sorted(catalog.subjects):
        lines.append(f'    "{subject}": {{')
        for state in sorted(catalog.subjects[subject].transitions):
            targets = sorted(catalog.subjects[subject].transitions[state])
            if targets:
                rendered = ", ".join(f'"{target}"' for target in targets)
                lines.append(f'        "{state}": frozenset({{{rendered}}}),')
            else:
                lines.append(f'        "{state}": frozenset(),')
        lines.append("    },")
    lines.append("}")
    return lines


def _render_string_set(name: str, values: list[str]) -> list[str]:
    if not values:
        return [f"{name}: frozenset[str] = frozenset()"]
    lines = [f"{name}: frozenset[str] = frozenset({{"]
    lines.extend(f'    "{value}",' for value in sorted(values))
    lines.append("})")
    return lines


def _render_verdict_enum() -> list[str]:
    return [
        "class VerdictOutcome(str, Enum):",
        '    """Trinary verdict outcome (I3); `indeterminate` carries a mandatory reason."""',
        "",
        '    POSITIVE = "positive"',
        '    NEGATIVE = "negative"',
        '    INDETERMINATE = "indeterminate"',
    ]


def _render_command_base() -> list[str]:
    return [
        "class _CommandBase(BaseModel):",
        '    model_config = ConfigDict(frozen=True, extra="forbid")',
        "",
        "    subject_key: str",
    ]


def _render_command_class(command_type: str, spec: CommandSpec) -> list[str]:
    lines = [
        f"class {_class_name(command_type)}(_CommandBase):",
        f'    command_type: Literal["{command_type}"] = "{command_type}"',
    ]
    if spec.subject_type is None:
        lines.append("    subject_type: str")
    else:
        lines.append(f'    subject_type: Literal["{spec.subject_type}"] = "{spec.subject_type}"')
    for field_name, field_type in spec.fields.items():
        lines.append(f"    {field_name}: {_FIELD_ANNOTATIONS[field_type]}")
    verdict_fields = [name for name, kind in spec.fields.items() if kind == "verdict_outcome"]
    for verdict_field in verdict_fields:
        lines.extend([
            "",
            '    @model_validator(mode="after")',
            f"    def _require_reason_when_{verdict_field}_indeterminate(self) -> {_class_name(command_type)}:",
            f"        if self.{verdict_field} is VerdictOutcome.INDETERMINATE and not self.reason:",
            f"            msg = \"{verdict_field} 'indeterminate' requires a reason\"",
            "            raise ValueError(msg)",
            "        return self",
        ])
    return lines


def _render_command_union(catalog: Catalog) -> list[str]:
    class_names = [_class_name(command_type) for command_type in sorted(catalog.commands)]
    lines = ["Command: TypeAlias = Annotated[", f"    {class_names[0]}"]
    lines.extend(f"    | {name}" for name in class_names[1:])
    lines[-1] += ","
    lines.extend(['    Field(discriminator="command_type"),', "]"])
    return lines


def _render_parse_command() -> list[str]:
    return [
        "_COMMAND_ADAPTER: TypeAdapter[Command] = TypeAdapter(Command)",
        "",
        "",
        "def parse_command(data: Mapping[str, object]) -> Command:",
        '    """Validate a raw payload against the generated vocabulary; unknown command types fail."""',
        "    return _COMMAND_ADAPTER.validate_python(data)",
    ]


def render_module(catalog: Catalog) -> str:
    """Render the generated module deterministically (sorted subjects, states, commands)."""
    recorded = [subject for subject in catalog.subjects if catalog.subjects[subject].ownership == "recorded"]
    backfill_only = [command for command, spec in catalog.commands.items() if spec.backfill_only]
    # Constant assignments are separated by one blank line; class and def blocks by two,
    # matching what `ruff format` enforces so regeneration is format-stable.
    constant_blocks = [
        _render_transitions(catalog),
        ["SUBJECT_TYPES: frozenset[str] = frozenset(TRANSITIONS)"],
        _render_string_set("RECORDED_SUBJECT_TYPES", recorded),
        _render_string_set("COMMAND_TYPES", sorted(catalog.commands)),
        _render_string_set("BACKFILL_ONLY_COMMAND_TYPES", backfill_only),
    ]
    definition_blocks = [_render_verdict_enum(), _render_command_base()]
    definition_blocks.extend(
        _render_command_class(command, catalog.commands[command]) for command in sorted(catalog.commands)
    )
    definition_blocks.append(_render_command_union(catalog))
    definition_blocks.append(_render_parse_command())
    lines = _render_header(catalog)
    for block in constant_blocks:
        lines.append("")
        lines.extend(block)
    for block in definition_blocks:
        lines.extend(["", ""])
        lines.extend(block)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: write the generated module, or verify it with --check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed module is current")
    args = parser.parse_args(argv)
    rendered = render_module(load_catalog())
    if args.check:
        if GENERATED_PATH.read_text() != rendered:
            print(f"{GENERATED_PATH} is stale — run: uv run python -m pulse_core.catalog_gen")
            return 1
        return 0
    GENERATED_PATH.write_text(rendered)
    print(f"wrote {GENERATED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
