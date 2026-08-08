"""The §4.4 producer policy as a pure classifier over producer source (producer-ingress-policy 1.1).

§4.4 of `design/migration/ocean-to-pulse-adaptation-plan.md` is a classification test over producer
schemas: does the event name a state that lives in the catalog? Then it routes through the ledger's
command API. The catalog is the boundary, mechanically checkable in CI. This module is that check —
extraction plus classification, no I/O beyond the files it is handed and no imports of scanned code.

**Extraction is AST-based, over three vocabulary surfaces** (design decision 2). `ast.parse` per
file; a producer service importing its dependency closure at gate time would be both slow and
fresh-clone-fragile.

- *State vocabularies* — `Literal[...]` aliases and annotations, enum classes, frozen string-set
  constants.
- *Entity/subject-type declarations* — values of `entity_type`/`subject_type` fields and
  `EntityType`-style `Literal` aliases.
- *Event-type addressing* — string constants assigned or passed as `event_type`, split on the
  first dot.

**A finding requires subject addressing, and matching is subject-scoped** (design decision 3, as
narrowed at G_MECE). An element flags only when it addresses a catalog subject:

- an entity/subject-type value *equal to* a subject name — `device_association` is not `device`;
- an event type whose prefix is a subject AND whose remaining segment, or a payload value in the
  same call or dict, names one of *that subject's* declared states. Bare prefix never flags:
  ocean's real `device.associated` stays green because `associated` is not a device state, while a
  planted `enrollment.active` is red because `active` is an enrollment state;
- a state vocabulary of two or more values forming a subset of *exactly one* subject's declared
  state set. Two-value floor plus the subset test is what keeps `AlertStatus` and `TicketStatus`
  green while `Literal["screened", "outreach", "converted"]` is red. A vocabulary fitting two
  subjects identifies neither. Single bare words never flag.

**The failure message is part of the contract** (design decision 7): every finding renders as
`<file>:<element> asserts <subject> state(s) <states>` — or, for a subject-addressing declaration
carrying no state vocabulary, `<file>:<element> declares catalog subject <subject>` — and the
report ends with the fixed `DISPOSITION` line. Spec'd, so it cannot rot into an assert diff.

The catalog comes from `pulse_core.generated.TRANSITIONS`, the pinned programmatic surface — never
the retired seed, the Snowflake rows, or generator internals. `transitions` is injectable so tests
pin classification semantics against a fixture catalog rather than a coincidence of the current one.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pulse_core.generated import TRANSITIONS

StateCatalog = Mapping[str, Mapping[str, frozenset[str]]]

DISPOSITION = (
    "Disposition (§4.4): a producer schema may not name a catalog state. Convert the emit to a "
    "command through the ledger write path (pulse_core.submit_command); the non-subject facts it "
    "also carries keep emitting directly. Only an adjudicated name-collision false positive may be "
    "suppressed, and only with a written justification, in "
    "packages/ocean/producer-policy-suppressions.yaml. See packages/ocean/docs/producer-policy.md."
)

EMPTY_REPORT = "No producer-policy findings."

_ENTITY_FIELDS = frozenset({"entity_type", "subject_type"})
_ENTITY_ALIAS_SUFFIXES = ("EntityType", "SubjectType")
_EVENT_FIELD = "event_type"
_EVENT_ALIAS_SUFFIX = "EventType"
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"})

DeclarationKind = Literal["states", "entity", "event"]


@dataclass(frozen=True, order=True)
class Finding:
    """One producer element that addresses a catalog subject.

    `states` is empty when the element addresses a subject without naming states — an
    `entity_type="referral"` declaration. Ordering is field order, which is also report order.
    """

    file: str
    element: str
    subject: str
    states: tuple[str, ...] = ()

    def render(self) -> str:
        """The fixed one-line rendering of this finding (design decision 7)."""
        if not self.states:
            return f"{self.file}:{self.element} declares catalog subject {self.subject}"
        return f"{self.file}:{self.element} asserts {self.subject} state(s) {', '.join(self.states)}"


@dataclass(frozen=True)
class _Declaration:
    """One extracted vocabulary, before classification.

    `context` carries the other string constants of the same call or dict — the "accompanying
    payload" an event-type declaration may hide its state in. It is deliberately empty for
    `Literal` aliases: the sibling values of a union are alternatives, not a payload.
    """

    element: str
    kind: DeclarationKind
    values: tuple[str, ...]
    context: tuple[str, ...] = ()


# --- Extraction ----------------------------------------------------------------------------


def _string_constants(node: ast.AST) -> tuple[str, ...]:
    return tuple(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def _is_literal_subscript(node: ast.expr) -> bool:
    base = node.value if isinstance(node, ast.Subscript) else None
    if isinstance(base, ast.Name):
        return base.id == "Literal"
    return isinstance(base, ast.Attribute) and base.attr == "Literal"


def _is_frozenset_call(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset"


def _string_values(node: ast.expr) -> tuple[str, ...]:
    """The string vocabulary a value or annotation node declares, if it declares one statically."""
    if isinstance(node, ast.Constant):
        return (node.value,) if isinstance(node.value, str) else ()
    if isinstance(node, ast.Subscript) and _is_literal_subscript(node):
        return _string_constants(node.slice)
    if isinstance(node, ast.Set):
        return _string_constants(node)
    if _is_frozenset_call(node):
        return _string_constants(node)
    return ()


def _kind_for_name(name: str) -> DeclarationKind:
    if name in _ENTITY_FIELDS or name.endswith(_ENTITY_ALIAS_SUFFIXES):
        return "entity"
    if name == _EVENT_FIELD or name.endswith(_EVENT_ALIAS_SUFFIX):
        return "event"
    return "states"


def _is_enum_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
        if name in _ENUM_BASES or name.endswith("Enum"):
            return True
    return False


def _enum_member_values(node: ast.ClassDef) -> tuple[str, ...]:
    values: list[str] = []
    for stmt in node.body:
        value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            values.append(value.value)
    return tuple(values)


@dataclass
class _Extractor(ast.NodeVisitor):
    """Collects declarations with their qualified element names. One pass, no imports."""

    declarations: list[_Declaration] = field(default_factory=list)
    _scope: list[str] = field(default_factory=list)

    def _qualified(self, name: str) -> str:
        return ".".join([*self._scope, name])

    def _record(self, name: str, kind: DeclarationKind, values: Sequence[str], context: Sequence[str] = ()) -> None:
        element = self._qualified(name)
        if kind == "entity":
            self.declarations.append(_Declaration(element, "entity", tuple(values)))
            return
        addressed = tuple(v for v in values if "." in v)
        if addressed:
            self.declarations.append(_Declaration(element, "event", addressed, tuple(context)))
        bare = tuple(v for v in values if "." not in v)
        if bare and kind == "states":
            self.declarations.append(_Declaration(element, "states", bare))

    def _declare(self, name: str, node: ast.expr, context: Sequence[str] = ()) -> None:
        values = _string_values(node)
        if values:
            self._record(name, _kind_for_name(name), values, context)

    def _in_scope(self, name: str, node: ast.AST) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if _is_enum_class(node):
            self._record(node.name, "states", _enum_member_values(node))
        self._in_scope(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._in_scope(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._in_scope(node.name, node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._declare(target.id, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        target = node.target
        name = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ""
        if name:
            self._declare(name, node.annotation)
            if node.value is not None:
                self._declare(name, node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        context = _string_constants(node)
        for keyword in node.keywords:
            if keyword.arg:
                self._declare(keyword.arg, keyword.value, context)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        context = _string_constants(node)
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self._declare(key.value, value, context)
        self.generic_visit(node)


# --- Classification ------------------------------------------------------------------------


def _states_of(catalog: StateCatalog, subject: str) -> frozenset[str]:
    return frozenset(catalog[subject])


def _classify_entity(decl: _Declaration, file: str, catalog: StateCatalog) -> list[Finding]:
    return [Finding(file, decl.element, value) for value in decl.values if value in catalog]


def _classify_event(decl: _Declaration, file: str, catalog: StateCatalog) -> list[Finding]:
    findings: list[Finding] = []
    for value in decl.values:
        subject, _, remainder = value.partition(".")
        if subject not in catalog:
            continue
        states = _states_of(catalog, subject)
        named = {segment for segment in remainder.split(".") if segment in states}
        named |= {carried for carried in decl.context if carried in states}
        if named:
            findings.append(Finding(file, decl.element, subject, tuple(sorted(named))))
    return findings


def _classify_states(decl: _Declaration, file: str, catalog: StateCatalog) -> list[Finding]:
    values = frozenset(decl.values)
    if len(values) < 2:
        return []
    subjects = [subject for subject in catalog if values <= _states_of(catalog, subject)]
    if len(subjects) != 1:
        return []
    return [Finding(file, decl.element, subjects[0], tuple(sorted(values)))]


def _classify(decl: _Declaration, file: str, catalog: StateCatalog) -> list[Finding]:
    if decl.kind == "entity":
        return _classify_entity(decl, file, catalog)
    if decl.kind == "event":
        return _classify_event(decl, file, catalog)
    return _classify_states(decl, file, catalog)


# --- Public surface ------------------------------------------------------------------------


def classify_source(file: str, source: str, *, transitions: StateCatalog = TRANSITIONS) -> list[Finding]:
    """Classify one producer source text against the catalog. Pure: parses text, reads nothing.

    `file` is the path reported in findings; it is never opened. Source that does not parse
    yields no finding — a syntax error is the type checker's failure to report, not this gate's.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    extractor = _Extractor()
    extractor.visit(tree)
    findings = {finding for decl in extractor.declarations for finding in _classify(decl, file, transitions)}
    return sorted(findings)


def classify_files(
    paths: Iterable[Path],
    *,
    root: Path | None = None,
    transitions: StateCatalog = TRANSITIONS,
) -> list[Finding]:
    """Classify each handed-in file, reporting paths relative to `root`. Reads only these files."""
    findings: list[Finding] = []
    for path in sorted(paths):
        reported = path.relative_to(root).as_posix() if root else path.as_posix()
        findings.extend(classify_source(reported, path.read_text(encoding="utf-8"), transitions=transitions))
    return sorted(findings)


def render_report(findings: Sequence[Finding]) -> str:
    """The gate's failure text: every finding, then the fixed §4.4 disposition line."""
    if not findings:
        return EMPTY_REPORT
    return "\n".join(finding.render() for finding in findings) + "\n\n" + DISPOSITION
