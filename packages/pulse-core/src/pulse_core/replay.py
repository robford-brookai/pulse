"""The kit's replay facility: a read-only `PulseCoreClient` resolved from the environment.

`PulseCoreClient.subject_history` is the ledger's replay surface (pulse-demo-closeout design
decision 5) — one subject's committed events, in ledger sequence, over HTTP. This module owns the
two environment variables that reach it, and it lives in `pulse_core` rather than in the connector
that replays for a reason the connector-kit spec states: a connector holds exactly *one* writer
credential of its own, and the gate in `tests/test_connector_credential_gate.py` enforces it. The
replay credential is the kit's facility, not the connector's second credential — the same standing
the cursor writer-state facility already has.

So `twenty_projection.rebuild` names no token: it asks here, and the credential's name is stated
once, in the kit, for every connector that ever needs to repaint itself from the journal.

The credential is read-only by intent, not by mechanism: the ledger's authorization model is one
bearer token per writer, and the history route accepts the same credential every other route does
(the 1.3 read is additive and holds no separate read scope). What the projection must never hold is
a ledger *database* credential — a DSN, a driver, a direct table read — and it does not: this is
the command API over HTTP, nothing more.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from pulse_core.client import PulseCoreClient

#: Where the command API is. The same variable every other connector reads for it.
REPLAY_BASE_URL_ENV_VAR = "PULSE_CORE_BASE_URL"

#: The bearer credential a replay read authenticates with. Named here, held nowhere in code.
REPLAY_TOKEN_ENV_VAR = "PULSE_CORE_REPLAY_TOKEN"  # noqa: S105 — a variable name, not a secret


class ReplayStartupError(RuntimeError):
    """The replay environment is incomplete — names every absent variable, never a value."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"replay reads are not configured — set: {', '.join(missing)}")


def replay_client_from_env(
    env: Mapping[str, str] | None = None,
    *,
    writer_id: str,
    transport: httpx.BaseTransport | None = None,
) -> PulseCoreClient:
    """A client for reading committed history, or a startup failure naming what is missing.

    An empty value counts as missing: an unset secret reaches a job as an empty string, and
    treating that as present would authenticate against nothing and read an empty history — the
    one answer a rebuild must never confuse with "this subject has no events".

    `writer_id` is the caller's own identity. It reaches nothing on a read path (it seeds the
    idempotency key of a *submitted* command), and is required rather than defaulted so no caller
    can replay anonymously.
    """
    environment = os.environ if env is None else env
    missing = tuple(name for name in (REPLAY_BASE_URL_ENV_VAR, REPLAY_TOKEN_ENV_VAR) if not environment.get(name))
    if missing:
        raise ReplayStartupError(missing)
    return PulseCoreClient(
        environment[REPLAY_BASE_URL_ENV_VAR],
        writer_id=writer_id,
        token=environment[REPLAY_TOKEN_ENV_VAR],
        transport=transport,
    )
