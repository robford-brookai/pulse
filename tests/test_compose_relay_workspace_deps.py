"""The compose relay must mount and install every workspace dependency of pulse-ledger.

The `ledger-relay` service in `packages/ocean/infra/docker-compose.yml` installs pulse-ledger
by pip from mounted paths — a workspace dependency (`[tool.uv.sources] ... workspace = true`)
exists on no index, so pip can satisfy it only from another mounted path in the same install.
When pulse-ledger gained its `twenty-projection` dependency, the compose file was not updated
and the relay crash-looped on `pip install` while `--wait` still reported it Healthy; demo1's
queue assertion was the first thing to notice, days later (2026-08-30). This gate makes that
drift a test failure at the PR that introduces the dependency: offline, file-reads only, so it
stays inside `task check`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomllib
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]

_PULSE_LEDGER_PYPROJECT = _REPO_ROOT / "packages" / "pulse-ledger" / "pyproject.toml"
_COMPOSE_FILE = _REPO_ROOT / "packages" / "ocean" / "infra" / "docker-compose.yml"


def _pulse_ledger_workspace_deps() -> set[str]:
    data = tomllib.loads(_PULSE_LEDGER_PYPROJECT.read_text())
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    return {name for name, spec in sources.items() if spec.get("workspace") is True}


def _relay_service() -> dict[str, Any]:
    compose = yaml.safe_load(_COMPOSE_FILE.read_text())
    return compose["services"]["ledger-relay"]


def test_every_workspace_dep_is_installed_in_the_relay_container() -> None:
    deps = _pulse_ledger_workspace_deps()
    assert deps, "pulse-ledger declares no workspace deps — if that is real, retire this gate"

    relay = _relay_service()
    command = str(relay["command"])
    installed = set(re.findall(r"(?<=\s)/([\w-]+)", command))

    missing = {dep for dep in deps if dep not in installed}
    assert not missing, (
        f"pulse-ledger workspace deps {sorted(missing)} are not pip-installed by the "
        f"ledger-relay compose command — pip cannot resolve a workspace package from an index, "
        f"so the relay will crash-loop exactly as it did for twenty-projection (2026-08-30). "
        f"Add '/<dep>' to the install list and a matching read-only volume."
    )


def test_every_installed_path_has_a_matching_volume_mount() -> None:
    relay = _relay_service()
    command = str(relay["command"])
    installed = set(re.findall(r"(?<=\s)/([\w-]+)", command))
    volumes = [str(v) for v in relay["volumes"]]
    mounted = {v.split(":")[1].lstrip("/") for v in volumes}

    unmounted = {path for path in installed if path not in mounted}
    assert not unmounted, (
        f"the ledger-relay compose command pip-installs {sorted(unmounted)} but mounts no "
        f"volume at those paths — the install fails at container start"
    )
