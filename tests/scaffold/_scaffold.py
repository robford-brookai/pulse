"""Shared helpers for the scaffold gates.

These tests validate the scaffold itself — its structure, tooling wiring, documented contract,
and glue scripts — rather than the packaged library. See README.md "Quality Gates".

Gate order (structural and cheap first, end-to-end last):
    1 structure -> 2 toolchain -> 3 config -> 4 commands (|| 5 glue, 6 edges) -> 7 hooks
    -> 8 docs -> 9 golden

Gates 2, 4 and 7 are shell scripts in this directory, not pytest modules: they assert on the
installed toolchain and on git hook behaviour, which is better expressed as a script than as
collected tests. Run them directly.
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

# tomllib is stdlib from 3.11; .github/workflows/main.yml also tests 3.10, where the
# `tomli` dev dependency backfills it.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = [
    "DATA",
    "ROOT",
    "git",
    "have",
    "is_template",
    "load_script",
    "template_only",
    "tomllib",
]

# tests/scaffold/conftest.py -> tests/ -> repo root
ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


def have(cli: str) -> bool:
    """True if `cli` resolves on PATH."""
    return shutil.which(cli) is not None


def load_script(name: str) -> ModuleType:
    """Import a module from scripts/ by path, without mutating sys.path.

    The glue scripts are CLI entry points, not an installed package, so they cannot be imported
    normally. Loading by file location keeps the import graph explicit.
    """
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run git and capture output. Never raises on non-zero — callers assert on returncode."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def is_template() -> bool:
    """True in repo-ade itself, false in a repo generated from it.

    Some gates check the template's own documentation contract — that the README's Taskfile
    snippet matches Taskfile.yml byte for byte, that the target tree lists every committed path.
    Once generated, a project owns those documents and there is nothing template-shaped left to
    verify, so those gates skip rather than fail.

    The git remote is the discriminator. The obvious alternative — looking for
    .ade-template-version — is circular for the one gate that exists to catch a stamp wrongly
    committed to the template.
    """
    origin = git("remote", "get-url", "origin").stdout.strip()
    if not origin:
        return True  # no remote: assume the template, so gates fail loudly rather than skip
    return origin.rstrip("/").removesuffix(".git").endswith("/repo-ade")


template_only = pytest.mark.skipif(
    not is_template(),
    reason="checks the template's own docs contract; a generated repo owns these files",
)


# CI (.github/workflows/main.yml) installs uv and Python but not go-task, openspec or openlore.
# Gates that shell out to those CLIs skip with a visible reason instead of failing the matrix.
# cat2_toolchain.sh is the gate that asserts they are installed — run it locally.
requires_task = pytest.mark.skipif(not have("task"), reason="go-task not installed")
requires_openlore = pytest.mark.skipif(not have("openlore"), reason="openlore not installed")
requires_openspec = pytest.mark.skipif(not have("openspec"), reason="openspec not installed")
