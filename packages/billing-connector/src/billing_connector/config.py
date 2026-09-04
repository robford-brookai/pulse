"""Connector configuration — one credential name, the queue and ledger endpoints, staleness
(task 1.2, spec: "One credential, names in config, values from the environment").

`Config` holds exactly one writer credential *name* — `BILLING_CONNECTOR_TOKEN`, the environment
variable the connector's actual token lives in — never the token's value. Everything else
`from_env()` resolves is a plain configuration value (a URL, a duration) read straight from the
environment and held on the frozen dataclass. `credential_name` is a constant, not itself sourced
from the environment: it names which variable holds the secret so `declare.py` (task 2.2) reads
`os.environ[config.credential_name]` at the one place it is used, and no secret value is ever
constructed, stored, or defaulted here. `from_env()` still requires that variable to be *set* —
startup fails naming it like every other required value — without ever reading or retaining what
it is set to.

`ledger_base_url` is the command-API base URL (mirrors `verdict_relay.production`'s
`PULSE_CORE_BASE_URL_ENV_VAR`) — an HTTP endpoint, never a database connection string. The
connector holds no ledger DSN and no `pulse_ledger` import (spec: "holds no ledger database
connection string"); reads go through the bus, writes through the command API.

`verdict_types` is deliberately not a field: the registered set is `billing.rules.registry`'s
fact, not a configuration value or an environment variable (spec: "The connector evaluates the
registered verdict types" — the set the registry lists, not a number pinned here). `registry.py`
landed in task 1.3; `Config.verdict_types()` still imports it by dynamic name rather than a static
`from billing.rules import registry`, so `RegistryUnavailableError` stays a real (if now
defensive-only) failure mode — an install missing the `billing` package's registry module,
rather than the ordinary case.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

# Deliberately imported for no symbol config.py itself calls: a package's `src/` tree importing
# `pulse_core.connector` anywhere is what brings it under the credential-posture gate's discovery
# scan (`pulse_core` `test_connector_credential_gate.py`: "A package is 'under the connector
# convention' if any file in its `src/` tree imports from `pulse_core.connector`"). Task 1.1
# deliberately withheld this import so the gate would not discover a package with no config yet;
# this module is where the connector-pattern spec requirement 1.2 satisfies pins it. `service.py`
# (wave 1) is where the kit's consume loop is actually driven.
import pulse_core.connector as _connector_kit

#: This connector's own writer credential *name* — the environment variable its actual token
#: lives in. A constant, not read from the environment: what varies by deploy is the token's
#: value, never which variable holds it.
TOKEN_ENV_VAR = "BILLING_CONNECTOR_TOKEN"  # noqa: S105 — an env var name, not a secret

#: The connector's own inbound queue (the kit's consume loop reads from this URL — `service.py`,
#: wave 1).
QUEUE_URL_ENV_VAR = "BILLING_CONNECTOR_QUEUE_URL"

#: The command-API base URL every declared verdict and transition is submitted through
#: (`declare.py`, task 2.2). An HTTP endpoint, never a ledger connection string.
LEDGER_BASE_URL_ENV_VAR = "BILLING_CONNECTOR_LEDGER_BASE_URL"

#: Optional: how old a subject's fact watermark (`billing_engine.subject_facts.updated_at`) may
#: be before evaluation reports `indeterminate`/`awaiting_source` instead of running the rule
#: (design.md decision 5). Seconds, as a plain integer string.
STALE_AFTER_ENV_VAR = "BILLING_CONNECTOR_STALE_AFTER"

#: Default `stale_after` when `BILLING_CONNECTOR_STALE_AFTER` is unset. The dbt source this
#: mirrors is `verdict_run_audit` (`data-platform` `management/models/billing/verdict/
#: verdict_run_audit.sql`, per `packages/billing/docs/rule-port-map.md`'s
#: `stays-mart-side` row for that model) — its source-table recency check is the warehouse-side
#: precedent this connector's own watermark staleness replaces (design.md decision 5). That
#: model's pinned window value is not committed to this repo (seed gate 3: the dbt spike files
#: land in `data-platform`, not here) — 24 hours is a placeholder pending that commit, not a
#: ported number; `HANDOFF.md` carries the follow-up.
_DEFAULT_STALE_AFTER = timedelta(hours=24)

#: The connector kit module name, read off the deliberate governance-only import above so the
#: import itself is a real reference rather than an unused-import suppression comment — exposed
#: publicly so `test_config.py` can assert this module actually reaches `pulse_core.connector`.
CONNECTOR_KIT_MODULE_NAME = _connector_kit.__name__


class ConfigError(RuntimeError):
    """Every missing or invalid environment variable `from_env()` found, named at once.

    Before this class existed, `from_env()` raised on the first problem, so fixing a broken
    environment was an edit-rerun loop: set one variable, rerun, hit the next (devex finding 7,
    `.planning/reports/2026-09-02-devex-scorecard.md`). `from_env()` now checks every variable
    before raising, so one `ConfigError` names all of them together.

    `problems` holds the offending variable *names*, in the fixed order `from_env()` checks them
    — never a value, so a secret variable that happens to be invalid still can't leak through
    this exception. `str(error)` carries the human-readable detail: each variable, what type or
    unit `from_env()` expected of it, and that it comes from the environment.
    """

    def __init__(self, problems: Sequence[str], *, detail: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(detail))


class RegistryUnavailableError(RuntimeError):
    """`billing.rules.registry` (billing-connector task 1.3) could not be imported.

    Raised by `Config.verdict_types()` so a broken install fails naming the gap explicitly rather
    than returning a silent empty set — defensive only in the ordinary case, since the registry
    module ships with the `billing` package this connector already depends on.
    """

    def __init__(self) -> None:
        super().__init__(
            "billing.rules.registry is not importable; Config.verdict_types() has nothing to "
            "read from until the billing package's registry module is available"
        )


@dataclass(frozen=True, slots=True)
class Config:
    """This connector's full configuration, resolved once at startup by `from_env()`.

    `credential_name` is a name, never a value — see the module docstring. `queue_url` and
    `ledger_base_url` are resolved values. `stale_after` is the connector's own watermark
    staleness threshold (design.md decision 5), not a source-table recency read.
    """

    credential_name: str
    queue_url: str
    ledger_base_url: str
    stale_after: timedelta

    def verdict_types(self) -> frozenset[str]:
        """The verdict types this connector evaluates: whatever `billing.rules.registry` lists
        (spec: "The connector evaluates the registered verdict types"), read fresh on every call
        rather than cached at construction — the registry, not this config object, is the source
        of truth for the registered set.

        Raises `RegistryUnavailableError` if `billing.rules.registry` cannot be imported. Imported
        by dynamic name (`importlib`, not `from billing.rules import registry`) so this module
        typechecks under pyright strict before the registry exists — `getattr` on the loaded
        module, not a static attribute access pyright would need the module to resolve.
        """
        try:
            registry = importlib.import_module("billing.rules.registry")
        except ImportError as exc:
            raise RegistryUnavailableError from exc
        verdict_types = cast("Iterable[str]", getattr(registry, "VERDICT_TYPES"))  # noqa: B009
        return frozenset(verdict_types)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Resolve every value from the environment, checking all of them before raising, so one
        `ConfigError` names every missing or invalid variable at once (spec: "Startup SHALL fail
        with the missing variable's name if any value is absent"; devex finding 7 — a `from_env()`
        that stopped at the first problem turned a broken environment into an edit-rerun loop).

        `env` defaults to `os.environ`; tests pass a plain `dict` so this never touches the real
        process environment. The credential is checked for *presence* only — its value is never
        read into this function's return value, and never into a `ConfigError` either.
        """
        source = os.environ if env is None else env
        problems: list[str] = []
        detail: list[str] = []

        def _fail(name: str, *, expected: str, got: str | None = None) -> None:
            problems.append(name)
            reason = "is not set" if got is None else f"is invalid: expected {expected}, got {got!r}"
            detail.append(f"{name} (environment variable) {reason}")

        if TOKEN_ENV_VAR not in source:
            _fail(TOKEN_ENV_VAR, expected="a value naming the connector's writer credential")

        queue_url = source.get(QUEUE_URL_ENV_VAR)
        if queue_url is None:
            _fail(QUEUE_URL_ENV_VAR, expected="a URL string")

        ledger_base_url = source.get(LEDGER_BASE_URL_ENV_VAR)
        if ledger_base_url is None:
            _fail(LEDGER_BASE_URL_ENV_VAR, expected="a URL string")

        stale_after_raw = source.get(STALE_AFTER_ENV_VAR)
        stale_after = _DEFAULT_STALE_AFTER
        if stale_after_raw is not None:
            try:
                stale_after = timedelta(seconds=int(stale_after_raw))
            except ValueError:
                _fail(STALE_AFTER_ENV_VAR, expected="an integer number of seconds", got=stale_after_raw)

        if problems:
            raise ConfigError(problems, detail=detail)

        return cls(
            credential_name=TOKEN_ENV_VAR,
            # Both narrowed to `str` here: each was checked for `None` above, and any `None`
            # would have appended to `problems`, which would have raised just above instead.
            queue_url=cast("str", queue_url),
            ledger_base_url=cast("str", ledger_base_url),
            stale_after=stale_after,
        )
