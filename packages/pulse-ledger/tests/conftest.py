"""Throwaway-cluster Postgres fixtures for the ledger migration tests, plus sys.path setup.

The suite starts its own Postgres on a private unix socket — no TCP listener, so the
no-live-network test posture holds. It needs server binaries (initdb, pg_ctl, postgres)
in one directory: set PULSE_PG_BINDIR to point at one, otherwise discovery walks PATH
and the usual Homebrew/Debian install locations (GitHub's ubuntu runners ship Postgres
under /usr/lib/postgresql/*/bin). With no server available the Postgres-backed tests
skip, visibly, rather than fake the store.

The root `task test` run collects every package's tests with `--import-mode=importlib`, which
does not add a test module's directory to sys.path (unlike the default "prepend" mode) — so
`twenty_fixtures.py` (the Twenty webhook fixture loader/signer, shared by this task's tests and
later waves' — 2.1's mapping tests, 3.1's route tests) would not import under either mode without
this. Same fix `identity`'s and `ocean`'s conftests already use for their own sibling helper
modules.
"""

from __future__ import annotations

import glob
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"

_SERVER_BINARIES = ("initdb", "pg_ctl", "postgres")

# Newest install first when several versions are present; sorted so discovery is
# deterministic across machines.
_BINDIR_PATTERNS = (
    "/opt/homebrew/opt/postgresql@*/bin",
    "/usr/local/opt/postgresql@*/bin",
    "/usr/lib/postgresql/*/bin",
)


def _find_pg_bindir() -> Path | None:
    candidates: list[Path] = []
    env_dir = os.environ.get("PULSE_PG_BINDIR")
    if env_dir:
        candidates.append(Path(env_dir))
    initdb_on_path = shutil.which("initdb")
    if initdb_on_path:
        candidates.append(Path(initdb_on_path).parent)
    for pattern in _BINDIR_PATTERNS:
        candidates.extend(Path(p) for p in sorted(glob.glob(pattern), reverse=True))
    for candidate in candidates:
        if all((candidate / name).is_file() for name in _SERVER_BINARIES):
            return candidate
    return None


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """A session-lived Postgres cluster listening only on a private unix socket."""
    bindir = _find_pg_bindir()
    if bindir is None:
        pytest.skip("no Postgres server binaries found (set PULSE_PG_BINDIR to a bin dir with initdb/pg_ctl/postgres)")
    data_dir = tmp_path_factory.mktemp("pgdata")
    # Unix socket paths are capped near 100 chars and pytest tmp paths can exceed that,
    # so the socket gets its own short-lived directory under the system tmpdir.
    socket_dir = tempfile.mkdtemp(prefix="pulse-pg-")
    subprocess.run(  # noqa: S603
        [str(bindir / "initdb"), "-D", str(data_dir), "-U", "postgres", "--auth=trust", "-N"],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [
            str(bindir / "pg_ctl"),
            "-D",
            str(data_dir),
            "-l",
            str(data_dir / "postgres.log"),
            "-w",
            "-o",
            f"-c listen_addresses='' -k {socket_dir}",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield {"host": socket_dir, "user": "postgres"}
    finally:
        subprocess.run(  # noqa: S603
            [str(bindir / "pg_ctl"), "-D", str(data_dir), "-m", "immediate", "stop"],
            check=False,
            capture_output=True,
        )
        shutil.rmtree(socket_dir, ignore_errors=True)


_db_counter = itertools.count()


@pytest.fixture
def pg_database(pg_server: dict[str, str]) -> Iterator[dict[str, str]]:
    """A fresh database per test, dropped afterwards (grants and all)."""
    name = f"ledger_test_{next(_db_counter)}"
    with psycopg.connect(host=pg_server["host"], user=pg_server["user"], dbname="postgres", autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield {**pg_server, "dbname": name}
    with psycopg.connect(host=pg_server["host"], user=pg_server["user"], dbname="postgres", autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def database_url(pg_database: dict[str, str]) -> str:
    """SQLAlchemy URL for the per-test database, socket-only."""
    return f"postgresql+psycopg://{pg_database['user']}@/{pg_database['dbname']}?host={pg_database['host']}"


@pytest.fixture
def ledger_db(database_url: str, db: psycopg.Connection) -> psycopg.Connection:
    """The per-test database with the `ledger` schema migrated to head.

    For suites that exercise the write path rather than the migration itself. The connection is
    autocommit, so a transaction only exists where the code under test opens one — which is what
    makes the atomicity assertions mean something.
    """
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "head")
    return db


@pytest.fixture
def db(pg_database: dict[str, str]) -> Iterator[psycopg.Connection]:
    """Superuser autocommit connection to the per-test database."""
    with psycopg.connect(
        host=pg_database["host"],
        user=pg_database["user"],
        dbname=pg_database["dbname"],
        autocommit=True,
    ) as conn:
        yield conn
