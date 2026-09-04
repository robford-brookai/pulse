#!/usr/bin/env python
"""Demo 5 live preflight: the three preconditions `docs/runbooks/demo5-end-to-end.md` states for
`--live`, checked before a single stage runs.

1. **The dev API is on a current image** — the per-subject history route (`pulse_core.history`,
   PR #331) answers at all. A stale pod predating it answers 404 for the route itself, which is
   exactly the trap the billing-state 4.1 run fell into (`docs/process/env-vars-retreival.md`).
2. **The dev ledger schema is at the head this demo needs** — Alembic revision ``0005`` admits
   `communication_consent` (PR #336); without it stage 2's first commit fails on a check
   constraint before catalog validation runs.
3. **Dev Twenty carries the seeded demo card** — a `patientPrograms` record whose
   `canonicalPatientId` is the fixture patient's subject key and whose `programCode` is
   ``demo5``, the same already-seeded precondition `demo3_live_kanban_drag.py` states.

Every credential is read by NAME from the environment and never printed; failure messages name
the check, the variable, or a count — never a value. Exits nonzero if any check fails, listing
all of them, so one run tells you everything that is wrong.

Usage:
    scripts/demo/demo5_preflight.py            # all three checks
    scripts/demo/demo5_preflight.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CONSENT_ROW = REPO_ROOT / "scripts" / "demo" / "fixtures" / "consent_export_row.json"

#: Environment variable NAMES (the values are secrets or deployment facts, never in code).
LEDGER_URL_ENV = "PULSE_LEDGER_API_URL"
REPLAY_TOKEN_ENV = "PULSE_CORE_REPLAY_TOKEN"  # noqa: S105 — a variable name, not a secret
DATABASE_URL_ENV = "DATABASE_URL"
TWENTY_URL_ENV = "PULSE_TWENTY_DEV_URL"
TWENTY_TOKEN_ENV = "PULSE_TWENTY_DEV_TOKEN"  # noqa: S105 — a variable name, not a secret

#: The schema head this demo needs (migration 0005 admits `communication_consent`).
EXPECTED_ALEMBIC_HEAD = "0005"
#: The board object and the fixture program code the seeded card must carry.
BOARD_OBJECT_PLURAL = "patientPrograms"
DEMO_PROGRAM_CODE = "demo5"
#: A subject that cannot exist; the probe only asks whether the route is served.
PROBE_SUBJECT_PATH = "/subjects/preflight/preflight/events"


@dataclass(frozen=True)
class CheckResult:
    """One precondition's outcome: its name, whether it held, and a value-free message."""

    name: str
    ok: bool
    message: str


def fixture_subject_key(path: Path = FIXTURE_CONSENT_ROW) -> str:
    """The demo patient's subject key, read from the committed consent fixture."""
    return str(json.loads(path.read_text())["subject_key"])


def check_api_current(client: httpx.Client, base_url: str, token: str) -> CheckResult:
    """The history route exists on the running API: any answer but 404 means the image carries it."""
    url = base_url.rstrip("/") + PROBE_SUBJECT_PATH
    try:
        response = client.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    except httpx.HTTPError as error:
        return CheckResult("api-image", False, f"{LEDGER_URL_ENV} unreachable: {type(error).__name__}")
    if response.status_code == 404:
        return CheckResult(
            "api-image",
            False,
            "history route answers 404 — the dev API pod predates PR #331; redeploy the current image",
        )
    return CheckResult("api-image", True, f"history route served (HTTP {response.status_code})")


def check_migration(fetch_head: Callable[[], str]) -> CheckResult:
    """The ledger schema is at `EXPECTED_ALEMBIC_HEAD`."""
    try:
        head = fetch_head()
    except Exception as error:
        return CheckResult("ledger-schema", False, f"{DATABASE_URL_ENV} query failed: {type(error).__name__}")
    if head != EXPECTED_ALEMBIC_HEAD:
        return CheckResult(
            "ledger-schema",
            False,
            f"alembic_version is {head}, need {EXPECTED_ALEMBIC_HEAD} (migration 0005, PR #336) — run the migrator",
        )
    return CheckResult("ledger-schema", True, f"alembic_version {head}")


def _postgres_head(database_url: str) -> str:
    import psycopg  # local import: the offline smoke test never touches a database

    with psycopg.connect(database_url, connect_timeout=10) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version_pulse_ledger")
        row = cursor.fetchone()
    return "" if row is None else str(row[0])


def _iter_board_records(client: httpx.Client, base_url: str, token: str) -> Iterator[Mapping[str, Any]]:
    cursor: str | None = None
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        params: dict[str, Any] = {"limit": 60}
        if cursor is not None:
            params["starting_after"] = cursor
        response = client.get(
            f"{base_url.rstrip('/')}/rest/{BOARD_OBJECT_PLURAL}", params=params, headers=headers, timeout=30.0
        )
        response.raise_for_status()
        body = response.json()
        records = body.get("data", {}).get(BOARD_OBJECT_PLURAL, ())
        yield from records
        page = body.get("pageInfo") or {}
        if not page.get("hasNextPage") or not records:
            return
        cursor = str(records[-1]["id"])


def check_seeded_card(client: httpx.Client, base_url: str, token: str, subject_key: str) -> CheckResult:
    """One board record carries the fixture patient's subject key and the demo program code."""
    try:
        scanned = 0
        for record in _iter_board_records(client, base_url, token):
            scanned += 1
            if record.get("canonicalPatientId") == subject_key and record.get("programCode") == DEMO_PROGRAM_CODE:
                return CheckResult(
                    "seeded-card", True, f"seeded {BOARD_OBJECT_PLURAL} record found ({scanned} scanned)"
                )
    except httpx.HTTPError as error:
        return CheckResult("seeded-card", False, f"{TWENTY_URL_ENV} query failed: {type(error).__name__}")
    return CheckResult(
        "seeded-card",
        False,
        f"no {BOARD_OBJECT_PLURAL} record with programCode={DEMO_PROGRAM_CODE} for the fixture patient "
        f"({scanned} scanned) — seed the card per the runbook",
    )


def check_board_reachable(client: httpx.Client, base_url: str, token: str, run_id: str) -> CheckResult:
    """A `--run-id` walk seeds its own fresh patient's card, so the board only has to answer."""
    try:
        response = client.get(
            f"{base_url.rstrip('/')}/rest/{BOARD_OBJECT_PLURAL}",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        return CheckResult("seeded-card", False, f"{TWENTY_URL_ENV} query failed: {type(error).__name__}")
    return CheckResult("seeded-card", True, f"board reachable; the walk seeds the card for run id {run_id!r}")


def missing_names(env: Mapping[str, str]) -> list[str]:
    return [
        name
        for name in (LEDGER_URL_ENV, REPLAY_TOKEN_ENV, DATABASE_URL_ENV, TWENTY_URL_ENV, TWENTY_TOKEN_ENV)
        if not env.get(name)
    ]


def run_preflight(
    env: Mapping[str, str],
    *,
    client: httpx.Client | None = None,
    fetch_head: Callable[[], str] | None = None,
    subject_key: str | None = None,
    run_id: str | None = None,
) -> list[CheckResult]:
    """Run every check and return every result; the caller decides the exit code."""
    missing = missing_names(env)
    if missing:
        return [CheckResult("environment", False, "not set: " + ", ".join(missing))]
    http = client or httpx.Client()
    key = subject_key if subject_key is not None else fixture_subject_key()
    head = fetch_head or (lambda: _postgres_head(env[DATABASE_URL_ENV]))
    board_check = (
        check_seeded_card(http, env[TWENTY_URL_ENV], env[TWENTY_TOKEN_ENV], key)
        if run_id is None
        else check_board_reachable(http, env[TWENTY_URL_ENV], env[TWENTY_TOKEN_ENV], run_id)
    )
    results = [
        check_api_current(http, env[LEDGER_URL_ENV], env[REPLAY_TOKEN_ENV]),
        check_migration(head),
        board_check,
    ]
    if client is None:
        http.close()
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Demo 5 live preflight — image, schema head, seeded card.")
    parser.add_argument(
        "--run-id",
        default=None,
        metavar="ID",
        help="the walk will run with this --run-id and seed its own card; check the board answers instead",
    )
    return parser


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = run_preflight(env if env is not None else os.environ, run_id=args.run_id)
    print("=== Demo 5 preflight ===")
    for result in results:
        print(f"{'ok  ' if result.ok else 'FAIL'} {result.name}: {result.message}")
    failed = [r for r in results if not r.ok]
    if failed:
        print(f"preflight failed: {len(failed)} of {len(results)} checks")
        return 1
    print("preflight passed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
