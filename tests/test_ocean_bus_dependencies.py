"""Bus-client dependency hygiene for the ocean tree (task 6.6, DNA-769).

Two invariants, both of which have been violated in ways no other test caught:

1. ``confluent_kafka`` is gone from every dependency surface — package manifests,
   lockfiles, and Dockerfiles — and no source file outside the shared publisher
   (``libs/ocean-broker``) imports a bus client.
2. Each service's Dockerfile installs a distribution set that satisfies the
   third-party imports its ``src/`` actually makes. 5.6 found images pinning
   ``confluent-kafka`` while omitting ``ocean-broker``/``boto3`` entirely — an
   image that cannot start, invisible to every service test suite.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).parents[1]
OCEAN = REPO_ROOT / "packages" / "ocean"
SERVICES = OCEAN / "services"
LIBS = OCEAN / "libs"

BUS_CLIENT_MODULES = {"confluent_kafka", "kafka", "aiokafka"}

#: Import name → distributions that provide it (directly or as a declared
#: dependency the installer resolves). Only names that differ from their
#: distribution or arrive transitively need an entry; the default mapping is
#: the module name with underscores as hyphens.
MODULE_DISTS: dict[str, set[str]] = {
    "yaml": {"pyyaml"},
    "bson": {"pymongo", "motor"},
    "pymongo": {"pymongo", "motor"},
    "slack_sdk": {"slack-sdk", "slack-bolt"},
    "starlette": {"starlette", "fastapi"},
    "pydantic": {"pydantic", "fastapi"},
    "httpx": {"httpx", "anthropic"},
    "snowflake": {"snowflake-connector-python"},
    "boto3": {"boto3", "aioboto3"},
}

OCEAN_LIBS = {"ocean-events", "ocean-broker", "ocean-connector-mcp"}


def _normalize(requirement: str) -> str:
    """Reduce a requirement string to its lowercase distribution name."""
    return re.split(r"[\[<>=!~;@ ]", requirement.strip().strip('"').strip("'"), maxsplit=1)[0].lower()


def _lib_dependencies(lib: str, seen: set[str] | None = None) -> set[str]:
    """Distributions a local ocean lib declares, expanded through local libs."""
    seen = seen if seen is not None else set()
    if lib in seen:
        return set()
    seen.add(lib)
    with (LIBS / lib / "pyproject.toml").open("rb") as fh:
        deps = {_normalize(d) for d in tomllib.load(fh)["project"].get("dependencies", [])}
    for dep in sorted(deps & OCEAN_LIBS):
        deps |= _lib_dependencies(dep, seen)
    return deps


def _installed_distributions(dockerfile: Path) -> set[str]:
    """Distribution names a Dockerfile installs, expanded through local libs."""
    text = dockerfile.read_text().replace("\\\n", " ")
    installed: set[str] = set()
    for line in text.splitlines():
        if "pip install" not in line:
            continue
        for token in line.split("install", 1)[1].split():
            if token.startswith("-"):
                continue
            if "/" in token:
                name = token.rstrip("/").rsplit("/", 1)[-1]
                if name in OCEAN_LIBS:
                    installed.add(name)
                    installed |= _lib_dependencies(name)
                continue
            installed.add(_normalize(token))
    return installed


def _top_level_imports(py_file: Path) -> set[str]:
    """Top-level module names imported (absolutely) by a Python file."""
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _third_party_imports(src_dir: Path) -> set[str]:
    """Third-party imports across a source tree, stdlib and self excluded."""
    imports: set[str] = set()
    for py_file in sorted(src_dir.rglob("*.py")):
        imports |= _top_level_imports(py_file)
    return {name for name in imports if name not in sys.stdlib_module_names and name != "src"}


def _dependency_surfaces() -> list[Path]:
    """Every manifest, lockfile, and Dockerfile that can pin a bus client."""
    surfaces = [REPO_ROOT / "pyproject.toml", REPO_ROOT / "uv.lock"]
    for pattern in ("**/pyproject.toml", "**/uv.lock", "**/Dockerfile"):
        surfaces.extend(sorted(OCEAN.glob(pattern)))
    return surfaces


def test_confluent_kafka_absent_from_all_dependency_surfaces() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT)) for path in _dependency_surfaces() if "confluent" in path.read_text().lower()
    ]
    assert not offenders, f"confluent-kafka still referenced by: {offenders}"


def test_no_bus_client_import_outside_shared_publisher() -> None:
    source_dirs = [
        *sorted(SERVICES.glob("*/src")),
        *sorted(lib / "src" for lib in LIBS.iterdir() if lib.is_dir() and lib.name != "ocean-broker"),
        OCEAN / "scripts",
    ]
    offenders = {
        str(src_dir.relative_to(REPO_ROOT)): sorted(found)
        for src_dir in source_dirs
        if src_dir.is_dir() and (found := _third_party_imports(src_dir) & BUS_CLIENT_MODULES)
    }
    assert not offenders, f"bus-client imports outside ocean-broker: {offenders}"


def test_dockerfile_installs_satisfy_service_imports() -> None:
    failures: dict[str, list[str]] = {}
    for service in sorted(SERVICES.iterdir()):
        dockerfile, src_dir = service / "Dockerfile", service / "src"
        if not (dockerfile.is_file() and src_dir.is_dir()):
            continue
        installed = _installed_distributions(dockerfile)
        missing = [
            module
            for module in sorted(_third_party_imports(src_dir))
            if not (MODULE_DISTS.get(module, {module.replace("_", "-")}) & installed)
        ]
        if missing:
            failures[service.name] = missing
    assert not failures, f"Dockerfile installs do not cover src imports: {failures}"


def test_dockerfile_installs_no_bus_client_nothing_imports() -> None:
    failures: dict[str, list[str]] = {}
    for service in sorted(SERVICES.iterdir()):
        dockerfile, src_dir = service / "Dockerfile", service / "src"
        if not (dockerfile.is_file() and src_dir.is_dir()):
            continue
        imports = _third_party_imports(src_dir)
        stray = [
            dist
            for dist in ("confluent-kafka", "aioboto3")
            if dist in _installed_distributions(dockerfile)
            and not any(dist in MODULE_DISTS.get(module, {module.replace("_", "-")}) for module in imports)
        ]
        if stray:
            failures[service.name] = stray
    assert not failures, f"Dockerfiles install bus clients nothing imports: {failures}"
