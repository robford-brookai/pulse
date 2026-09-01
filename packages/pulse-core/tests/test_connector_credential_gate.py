"""Credential-posture gate — every package built on the connector kit (`pulse_core.connector`)
holds exactly one writer credential name, no ledger internals, and never lets a credential value
reach a log call (connector-kit spec: "One connector, one credential, no ledger internals").

A package is "under the connector convention" if any file in its `src/` tree imports from
`pulse_core.connector` — the same fact that makes a package a donor or a consumer of the kit
(today: consent-ingress, verdict-relay, twenty-projection). Discovery is filesystem-driven, so a
future connector — the billing engine (wave 2), say — joins this gate the moment it imports the
kit, with no gate edit required. `pulse_core` itself is excluded: it *is* the kit, not a consumer
of it.

Three checks per package, each backed by a pure scanning function so the "red against a planted
violation" half of this gate (`test_the_gate_catches_*` below) can exercise it against a synthetic
snippet without writing a broken file into the tree — the same posture `archaeology`'s credential
gate takes with its synthetic Mongo URIs:

- `credential_names`          — distinct ALL-CAPS `..._TOKEN` / `..._CREDENTIAL`-shaped string
  literals (plain or an f-string's literal shape), excluding the cursor writer-state facility's
  own credential (name contains `CURSOR`). That facility is sanctioned separately by the kit's
  durable-cursor contract (connector-kit spec, task 2.1: "durable cursor persisted through the
  ledger's writer-state facility") — it is not a second "writer credential" in the sense §4's
  requirement text uses the term, so it does not count against the ceiling of one.
- `ledger_internal_uses`      — an import of `pulse_ledger`, a raw DB driver import, or a
  DSN-shaped string literal. Any of these is a ledger connection or a ledger-internal surface a
  connector must never hold: writes go through the command API, reads through the bus.
- `log_call_credential_leaks` — a `logging`/`logger`/`print` call whose arguments name something
  credential-shaped (`token`, `credential`, `secret`, `password`, case-insensitive) or read
  straight from the environment (`os.environ[...]`, `environ.get(...)`, `getenv(...)`).

Every scanner works on file *text* (`ast.parse` for structure, `re` for literal shapes), so the
planted-fixture tests hand it a string that never touches disk.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES_ROOT = _REPO_ROOT / "packages"

#: A `..._TOKEN` / `..._CREDENTIAL` shaped string literal — plain, or the literal shape of an
#: f-string with every interpolation collapsed to `{}` by `_joined_str_shape` below, e.g.
#: `f"PULSE_TWENTY_{target.upper()}_TOKEN"` renders as `PULSE_TWENTY_{}_TOKEN`, which still ends
#: in the suffix that matters.
_CREDENTIAL_SHAPE = re.compile(r"^[A-Z][A-Z0-9_{}]*_(TOKEN|CREDENTIAL)$")

_LOG_CALL_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
_CREDENTIAL_LOOKING_NAME = re.compile(r"(token|credential|secret|password)", re.IGNORECASE)

_DSN_SHAPE = re.compile(r"(postgres(?:ql)?|mysql)(\+\w+)?://")
_DB_DRIVER_MODULES = {"psycopg2", "asyncpg", "sqlalchemy"}


def _joined_str_shape(node: ast.JoinedStr) -> str:
    """An f-string's literal shape: every interpolated `{...}` collapses to a bare `{}`."""
    parts = [
        value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "{}"
        for value in node.values
    ]
    return "".join(parts)


def credential_names(source: str) -> set[str]:
    """Distinct declared credential names in `source`, excluding the cursor facility's own."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        text: str | None = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = _joined_str_shape(node)
        if text and _CREDENTIAL_SHAPE.match(text) and "CURSOR" not in text:
            names.add(text)
    return names


def ledger_internal_uses(source: str) -> list[str]:
    """Ledger-internal surfaces `source` reaches for: a `pulse_ledger` import, a raw DB driver
    import, or a DSN-shaped string literal. Non-empty means a violation."""
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            offenders += [
                alias.name
                for alias in node.names
                if alias.name == "pulse_ledger" or alias.name.split(".")[0] in _DB_DRIVER_MODULES
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if node.module == "pulse_ledger" or root == "pulse_ledger" or root in _DB_DRIVER_MODULES:
                offenders.append(node.module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _DSN_SHAPE.search(node.value):
            offenders.append(node.value)
    return offenders


def log_call_credential_leaks(source: str) -> list[str]:
    """Log/print call sites whose arguments name or read a credential. Non-empty means a
    violation — the gate never repeats the offending value, only where it was found."""
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_log_call = (isinstance(func, ast.Attribute) and func.attr in _LOG_CALL_METHODS) or (
            isinstance(func, ast.Name) and func.id == "print"
        )
        if not is_log_call:
            continue
        call_desc = f"line {node.lineno}"
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name) and _CREDENTIAL_LOOKING_NAME.search(sub.id):
                    offenders.append(f"{call_desc}: credential-shaped name {sub.id!r}")
                elif isinstance(sub, ast.Attribute) and sub.attr == "environ":
                    offenders.append(f"{call_desc}: os.environ read inline")
                elif isinstance(sub, ast.Name) and sub.id in {"environ", "getenv"}:
                    offenders.append(f"{call_desc}: {sub.id}(...) read inline")
    return offenders


def _pulse_ledger_dependency(pkg_dir: Path) -> list[str]:
    """Belt-and-suspenders: the package never *declares* pulse-ledger as a dependency either."""
    pyproject = pkg_dir / "pyproject.toml"
    if pyproject.is_file() and re.search(r'["\']pulse-ledger["\']|^pulse-ledger\s*=', pyproject.read_text(), re.M):
        return [f"{pyproject.relative_to(_REPO_ROOT)}: declares pulse-ledger"]
    return []


def _imports_the_kit(source: str) -> bool:
    return bool(re.search(r"\bpulse_core\.connector\b|from\s+pulse_core\s+import[^\n]*\bconnector\b", source))


def discover_connector_packages() -> list[Path]:
    """Every package whose `src/` tree imports `pulse_core.connector` — the kit itself excluded."""
    packages = []
    for pkg_dir in sorted(_PACKAGES_ROOT.iterdir()):
        src = pkg_dir / "src"
        if pkg_dir.name == "pulse-core" or not src.is_dir():
            continue
        if any(_imports_the_kit(p.read_text()) for p in sorted(src.rglob("*.py"))):
            packages.append(pkg_dir)
    return packages


def _scan_package(pkg_dir: Path, scanner) -> list[str]:
    offenders: list[str] = []
    for py_file in sorted((pkg_dir / "src").rglob("*.py")):
        offenders += [f"{py_file.relative_to(_REPO_ROOT)}: {found}" for found in scanner(py_file.read_text())]
    return offenders


_CONNECTOR_PACKAGES = discover_connector_packages()


# --- The gate, run against the real tree -----------------------------------------------------


@pytest.mark.parametrize("pkg_dir", _CONNECTOR_PACKAGES, ids=lambda p: p.name)
def test_package_holds_exactly_one_credential_name(pkg_dir: Path) -> None:
    names: set[str] = set()
    for py_file in sorted((pkg_dir / "src").rglob("*.py")):
        names |= credential_names(py_file.read_text())
    assert len(names) == 1, f"{pkg_dir.name} declares {sorted(names)} — want exactly one credential name"


@pytest.mark.parametrize("pkg_dir", _CONNECTOR_PACKAGES, ids=lambda p: p.name)
def test_package_holds_no_ledger_internals(pkg_dir: Path) -> None:
    offenders = _scan_package(pkg_dir, ledger_internal_uses) + _pulse_ledger_dependency(pkg_dir)
    assert offenders == [], f"{pkg_dir.name} reaches ledger internals: {offenders}"


@pytest.mark.parametrize("pkg_dir", _CONNECTOR_PACKAGES, ids=lambda p: p.name)
def test_package_never_logs_a_credential_value(pkg_dir: Path) -> None:
    offenders = _scan_package(pkg_dir, log_call_credential_leaks)
    assert offenders == [], f"{pkg_dir.name} may log a credential: {offenders}"


def test_discovers_the_known_connector_packages() -> None:
    """Pins today's membership so a package silently dropping out of scope shows in a diff,
    without hand-listing every future connector — discovery stays generic on purpose."""
    discovered = {p.name for p in _CONNECTOR_PACKAGES}
    assert discovered >= {"consent-ingress", "verdict-relay", "twenty-projection"}


# --- The gate is live: red against a planted violation, green on the credential-free shape -----


def test_the_gate_catches_two_credential_names() -> None:
    fixture = 'FIRST_TOKEN_ENV_VAR = "PKG_FIRST_TOKEN"\nSECOND_TOKEN_ENV_VAR = "PKG_SECOND_TOKEN"\n'
    assert credential_names(fixture) == {"PKG_FIRST_TOKEN", "PKG_SECOND_TOKEN"}


def test_the_gate_excludes_the_cursor_facilitys_own_credential() -> None:
    fixture = 'WRITER_TOKEN_ENV_VAR = "PKG_WRITER_TOKEN"\nCURSOR_TOKEN_ENV_VAR = "PKG_CURSOR_TOKEN"\n'
    assert credential_names(fixture) == {"PKG_WRITER_TOKEN"}


def test_the_gate_reads_a_templated_credential_name() -> None:
    """The twenty-projection shape: the env var name is an f-string, not a plain literal."""
    fixture = (
        'def env_var_names(target):\n    return (f"PULSE_X_{target.upper()}_URL", f"PULSE_X_{target.upper()}_TOKEN")\n'
    )
    assert credential_names(fixture) == {"PULSE_X_{}_TOKEN"}


def test_the_gate_catches_a_ledger_internal_import() -> None:
    assert ledger_internal_uses("from pulse_ledger.identity import lookup_identifier\n") != []


def test_the_gate_catches_a_dsn_literal() -> None:
    assert ledger_internal_uses('LEDGER_DSN = "postgresql://ledger-host/pulse"\n') != []


def test_the_gate_does_not_flag_a_ledger_free_module() -> None:
    assert ledger_internal_uses('BASE_URL_ENV_VAR = "PULSE_CORE_BASE_URL"\n') == []


def test_the_gate_catches_a_credential_value_reaching_a_log_call() -> None:
    fixture = (
        "import logging\n"
        "import os\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def run():\n"
        '    token = os.environ["SOME_TOKEN"]\n'
        '    logger.info("token=%s", token)\n'
    )
    assert log_call_credential_leaks(fixture) != []


def test_the_gate_catches_an_inline_environ_read_in_a_log_call() -> None:
    fixture = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def run(environ):\n"
        '    logger.warning("failed for %s", environ["SOME_TOKEN"])\n'
    )
    assert log_call_credential_leaks(fixture) != []


def test_the_gate_does_not_flag_a_credential_free_log_call() -> None:
    fixture = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n\n"
        "def run(row_count):\n"
        '    logger.info("declared=%s", row_count)\n'
    )
    assert log_call_credential_leaks(fixture) == []
