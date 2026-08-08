"""The deploy entrypoint for the catalog release job (catalog-authority 4.3).

`task catalog:release` runs this module with the `linear:sync` posture — the credential state
decides between exactly three behaviours, and nothing is ever a silent no-op:

- **No `--apply`** (with or without credentials): print the rendered release plan to stdout and
  exit zero. Pure and offline — the plan is `render_release_script` over the newest released
  snapshot, and no connection is ever opened.
- **`--apply` without credentials**: exit nonzero naming exactly the missing environment
  variables. A deploy that silently skipped the release would leave the warehouse quietly stale.
- **`--apply` with credentials**: execute through `apply_release`, behind the 4.2 immutability
  guard (identical re-release → no-op, conflicting re-release → hard failure before any write).

What gets released is the newest version in `catalog/releases/MANIFEST.sha256`, read from its
frozen snapshot — not the head catalog file — so the release job and the immutability manifest
can never disagree about what a version contains. The breaking classification stamped into the
version row is the same diff `verify_ceremony` gates: the two newest manifest versions.

The snowflake driver is imported lazily inside the default connect factory, and only on a
credentialed `--apply`: `task check` and the plan path never import it, keeping the check
contract green on a credential-free runner (spec: "The check contract stays credential-free").
The target database is `SNOWFLAKE_DATABASE` when set, else the 4.1 placeholder — a release that
reaches Snowflake under the placeholder name was misconfigured, and the name says so.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from pulse_core.catalog_breaking import ReleaseClassification, classify_release
from pulse_core.catalog_gen import Catalog, load_catalog
from pulse_core.catalog_release import (
    ReleaseConfig,
    ReleaseConnection,
    ReleaseSource,
    apply_release,
    render_release_script,
    snapshot_checksum,
)
from pulse_core.catalog_snapshots import MANIFEST_NAME, RELEASES_DIR, read_manifest

# The warehouse credentials apply demands. Empty counts as missing: an unset Actions secret
# reaches the job as an empty string, and treating that as present would apply with garbage.
REQUIRED_CREDENTIALS = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")

# Optional: which account database homes the `catalog` schema — the change's one open question,
# pinned by the first credentialed deploy (ReleaseConfig.database placeholder until then).
DATABASE_VAR = "SNOWFLAKE_DATABASE"

ConnectFactory = Callable[[Mapping[str, str]], ReleaseConnection]


def missing_credentials(env: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(name for name in REQUIRED_CREDENTIALS if not env.get(name))


def _git_identity(env: Mapping[str, str]) -> tuple[str, str]:
    """The release's git provenance: the Actions env when present, local git otherwise."""
    commit = env.get("GITHUB_SHA") or _git("rev-parse", "HEAD")
    ref = env.get("GITHUB_REF") or _git("rev-parse", "--abbrev-ref", "HEAD")
    return commit, ref


def _git(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _classification(releases_dir: Path) -> ReleaseClassification:
    """The D18 diff of the two newest released versions — empty when there is no predecessor."""
    entries = read_manifest(releases_dir / MANIFEST_NAME)
    if len(entries) < 2:
        return ReleaseClassification(findings=())
    previous, current = entries[-2], entries[-1]
    return classify_release(
        load_catalog(releases_dir / previous.filename),
        load_catalog(releases_dir / current.filename),
    )


def build_release(
    releases_dir: Path = RELEASES_DIR,
    env: Mapping[str, str] | None = None,
) -> tuple[Catalog, ReleaseSource, ReleaseConfig]:
    """The complete release identity for the newest manifest version, from the frozen snapshot."""
    env = {} if env is None else env
    newest = read_manifest(releases_dir / MANIFEST_NAME)[-1]
    catalog = load_catalog(releases_dir / newest.filename)
    commit, ref = _git_identity(env)
    source = ReleaseSource(
        git_commit=commit,
        git_ref=ref,
        snapshot_checksum=snapshot_checksum(newest.version, releases_dir),
        classification=_classification(releases_dir),
    )
    database = env.get(DATABASE_VAR)
    config = ReleaseConfig(database=database) if database else ReleaseConfig()
    return catalog, source, config


class _DriverConnection:
    """The snowflake driver adapted to the one-method `ReleaseConnection` boundary."""

    def __init__(self, driver_connection: object) -> None:
        self._connection = driver_connection

    def execute(self, statement: str) -> list[tuple[object, ...]]:
        cursor = self._connection.cursor()  # type: ignore[attr-defined]
        cursor.execute(statement)
        return list(cursor.fetchall())


def _snowflake_connect(env: Mapping[str, str]) -> ReleaseConnection:
    """The default connect factory — the only place the snowflake driver is ever imported."""
    connector = importlib.import_module("snowflake.connector")
    kwargs: dict[str, str] = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "password": env["SNOWFLAKE_PASSWORD"],
    }
    if env.get(DATABASE_VAR):
        kwargs["database"] = env[DATABASE_VAR]
    return _DriverConnection(connector.connect(**kwargs))


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    connect: ConnectFactory | None = None,
) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(
        prog="catalog-release",
        description="Render (default) or apply (--apply) the newest released catalog version.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute the release against Snowflake (requires warehouse credentials)",
    )
    args = parser.parse_args(argv)

    catalog, source, config = build_release(env=env)

    if not args.apply:
        sys.stdout.write(render_release_script(catalog, source, config))
        return 0

    missing = missing_credentials(env)
    if missing:
        print(
            f"apply requested without warehouse credentials; missing environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2

    connection = (connect or _snowflake_connect)(env)
    result = apply_release(catalog, source, connection, config)
    print(f"catalog version {result.version}: {result.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
