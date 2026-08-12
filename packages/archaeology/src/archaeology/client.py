"""Read-only Mongo client factory, credentialed by reference only.

Connection posture is inherited from brookai/streamline's Mongo CDC service
(`repos/dacorom/mongo-stream/src/config.py` and `src/watcher.py` in that repo):
the same sync pymongo ``MongoClient``, the same bounded network waits
(server-selection / connect / socket timeouts, streamline's defaults), TLS on by
default (Atlas), env-sourced config that fails fast naming the missing variable.
Divergences from that pattern are decisions recorded in README.md, never
accidents — see docs/contracts/consumes.md.

Two deliberate divergences, both required by the read-only charter:

- credentials arrive as a secret-store *reference* (``env:NAME`` or
  ``file:PATH``), never a literal connection string — no ``MONGODB_URI`` with an
  embedded credential ever exists in this repo or its environment contract;
- the factory refuses to construct when the resolved user detectably holds
  write roles. The Atlas read-only role is the control; this refusal is defense
  in depth. When role detection is not permitted, construction proceeds.

No PHI can flow through this module: it builds clients and inspects role
metadata only. Error messages carry variable *names* and role names, never
values.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

# --- The BF-0a -> BF-0b env-var interface. Names only; values live in the ---
# --- DuploCloud secret store and the operator's session environment.      ---

ENV_HOST = "ARCHAEOLOGY_MONGO_HOST"
ENV_USER = "ARCHAEOLOGY_MONGO_USER"
ENV_PASSWORD_REF = "ARCHAEOLOGY_MONGO_PASSWORD_REF"  # noqa: S105 — env var *name*, not a secret
ENV_DB = "ARCHAEOLOGY_MONGO_DB"
ENV_TLS = "ARCHAEOLOGY_MONGO_TLS"
ENV_SERVER_SELECTION_TIMEOUT_MS = "ARCHAEOLOGY_MONGO_SERVER_SELECTION_TIMEOUT_MS"
ENV_CONNECT_TIMEOUT_MS = "ARCHAEOLOGY_MONGO_CONNECT_TIMEOUT_MS"
ENV_SOCKET_TIMEOUT_MS = "ARCHAEOLOGY_MONGO_SOCKET_TIMEOUT_MS"

#: The variables that must be set for the factory to construct at all.
REQUIRED_ENV_VARS: tuple[str, ...] = (ENV_HOST, ENV_USER, ENV_PASSWORD_REF)

#: Every variable this package reads — the documented interface, in one place.
ENV_VAR_NAMES: tuple[str, ...] = (
    *REQUIRED_ENV_VARS,
    ENV_DB,
    ENV_TLS,
    ENV_SERVER_SELECTION_TIMEOUT_MS,
    ENV_CONNECT_TIMEOUT_MS,
    ENV_SOCKET_TIMEOUT_MS,
)

# Streamline's bounded-wait defaults (mongo-stream src/config.py): every network
# wait raises instead of wedging the thread — their 2026-06-20 failure mode.
_DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 30_000
_DEFAULT_CONNECT_TIMEOUT_MS = 20_000
_DEFAULT_SOCKET_TIMEOUT_MS = 600_000
_DEFAULT_DB = "prod"  # streamline's MONGO_DB default

#: Built-in Mongo roles that grant any write, DDL, or user-admin capability.
#: Detection is best-effort by design — the Atlas role is the control.
WRITE_ROLES: frozenset[str] = frozenset({
    "readWrite",
    "readWriteAnyDatabase",
    "dbAdmin",
    "dbAdminAnyDatabase",
    "dbOwner",
    "userAdmin",
    "userAdminAnyDatabase",
    "clusterAdmin",
    "clusterManager",
    "restore",
    "root",
    "atlasAdmin",
})


class ArchaeologyError(Exception):
    """Base for every error this package raises."""


class MissingEnvVarsError(ArchaeologyError):
    """Required env vars are unset. Carries names only, never values."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"missing required env vars: {', '.join(missing)}")


class SecretRefError(ArchaeologyError):
    """The password reference is malformed or does not resolve.

    Subclasses build their own messages (tryceratops TRY003, the identity
    fixtures precedent) and name the reference form and the variable name,
    never a value.
    """


class SecretRefUnsetError(SecretRefError):
    """The ``env:NAME`` reference points at an env var that is unset."""

    def __init__(self, env_name: str) -> None:
        super().__init__(f"{ENV_PASSWORD_REF} points at env var {env_name}, which is unset")


class SecretRefFileMissingError(SecretRefError):
    """The ``file:PATH`` reference points at a file that does not exist."""

    def __init__(self) -> None:
        super().__init__(f"{ENV_PASSWORD_REF} points at a file that does not exist")


class SecretRefFormError(SecretRefError):
    """The reference is neither ``env:NAME`` nor ``file:PATH`` — a literal is refused."""

    def __init__(self) -> None:
        super().__init__(
            f"{ENV_PASSWORD_REF} must be a secret-store reference ('env:NAME' or 'file:PATH'), "
            "never a literal credential"
        )


class InvalidEnvValueError(ArchaeologyError):
    """A documented env var holds a value outside its accepted set."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} must be 'true' or 'false'")


class WriteRoleRefusedError(ArchaeologyError):
    """The resolved user detectably holds write roles; no client is returned."""

    def __init__(self, roles: tuple[str, ...]) -> None:
        self.roles = roles
        super().__init__(
            f"refusing to construct: resolved user holds write role(s) {', '.join(roles)}; "
            "this seam is read-only by charter (BF-0a)"
        )


def _parse_bool(name: str, raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise InvalidEnvValueError(name)


@dataclass(frozen=True)
class ArchaeologyConfig:
    """Connection parameters, sourced entirely from environment variables."""

    host: str
    user: str
    password_ref: str
    database: str = _DEFAULT_DB
    tls: bool = True
    server_selection_timeout_ms: int = _DEFAULT_SERVER_SELECTION_TIMEOUT_MS
    connect_timeout_ms: int = _DEFAULT_CONNECT_TIMEOUT_MS
    socket_timeout_ms: int = _DEFAULT_SOCKET_TIMEOUT_MS

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ArchaeologyConfig:
        """Build config from the documented env vars, failing fast with names.

        Every missing required variable is collected and reported in one raise —
        an operator fixes the whole set at once instead of replaying failures.
        """
        env = os.environ if environ is None else environ
        missing = tuple(name for name in REQUIRED_ENV_VARS if not env.get(name))
        if missing:
            raise MissingEnvVarsError(missing)
        return cls(
            host=env[ENV_HOST],
            user=env[ENV_USER],
            password_ref=env[ENV_PASSWORD_REF],
            database=env.get(ENV_DB, _DEFAULT_DB),
            tls=_parse_bool(ENV_TLS, env.get(ENV_TLS, "true")),
            server_selection_timeout_ms=int(
                env.get(ENV_SERVER_SELECTION_TIMEOUT_MS, str(_DEFAULT_SERVER_SELECTION_TIMEOUT_MS))
            ),
            connect_timeout_ms=int(env.get(ENV_CONNECT_TIMEOUT_MS, str(_DEFAULT_CONNECT_TIMEOUT_MS))),
            socket_timeout_ms=int(env.get(ENV_SOCKET_TIMEOUT_MS, str(_DEFAULT_SOCKET_TIMEOUT_MS))),
        )


def _resolve_secret_ref(ref: str, environ: dict[str, str] | None = None) -> str:
    """Resolve ``env:NAME`` or ``file:PATH`` to the secret value at runtime.

    A bare value is rejected: this seam never accepts a literal credential, so a
    connection secret cannot be smuggled in as the "reference" itself.
    """
    env = os.environ if environ is None else environ
    if ref.startswith("env:"):
        name = ref.removeprefix("env:")
        value = env.get(name)
        if not value:
            raise SecretRefUnsetError(name)
        return value
    if ref.startswith("file:"):
        path = Path(ref.removeprefix("file:"))
        if not path.is_file():
            raise SecretRefFileMissingError
        return path.read_text().strip()
    raise SecretRefFormError


def _detect_write_roles(client: Any) -> tuple[str, ...]:
    """Return the write roles the connection's user holds, where detectable.

    Uses ``connectionStatus`` (readable by any authenticated user on most
    deployments). When the deployment refuses the command, detection is not
    possible and the empty tuple is returned — the Atlas role is the control,
    this check is defense in depth (design decision 3).
    """
    try:
        status: dict[str, Any] = client.admin.command("connectionStatus")
    except PyMongoError:
        return ()
    roles: list[dict[str, Any]] = status.get("authInfo", {}).get("authenticatedUserRoles", [])
    return tuple(sorted({str(entry["role"]) for entry in roles if str(entry.get("role")) in WRITE_ROLES}))


def create_readonly_client(
    config: ArchaeologyConfig | None = None,
    *,
    client_cls: Callable[..., Any] | None = None,
    environ: dict[str, str] | None = None,
) -> Any:
    """Construct the read-only client, or refuse.

    Raises :class:`MissingEnvVarsError` before any network attempt when the
    documented variables are unset, :class:`SecretRefError` when the password
    reference does not resolve, and :class:`WriteRoleRefusedError` when the
    resolved user detectably holds write roles (the client is closed, nothing is
    returned).

    ``client_cls`` exists for tests, which fake the driver at this boundary —
    no test in this repo ever opens a socket.
    """
    cfg = config if config is not None else ArchaeologyConfig.from_env(environ)
    factory: Callable[..., Any] = client_cls if client_cls is not None else MongoClient[dict[str, Any]]
    password = _resolve_secret_ref(cfg.password_ref, environ)
    client: Any = factory(
        host=cfg.host,
        username=cfg.user,
        password=password,
        tls=cfg.tls,
        # Read-only by construction: retryable writes are off because no write
        # is ever issued; reads keep pymongo's retryable-read default.
        retryWrites=False,
        serverSelectionTimeoutMS=cfg.server_selection_timeout_ms,
        connectTimeoutMS=cfg.connect_timeout_ms,
        socketTimeoutMS=cfg.socket_timeout_ms,
    )
    write_roles = _detect_write_roles(client)
    if write_roles:
        client.close()
        raise WriteRoleRefusedError(write_roles)
    return client
