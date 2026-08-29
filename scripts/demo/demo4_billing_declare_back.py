#!/usr/bin/env python
"""Demo 4: live declare-back on dev (task 4.1) — the billing/coverage pairing against the real
mart and ledger.

Per the roadmap's demo convention: a runnable script under `scripts/demo/`, exits nonzero on any
failed assertion, stays out of `task check`. Like Demos 1 and 3 this one is *live* — it needs a
reachable dev Snowflake mart (`VERDICT_RELAY_*` credentials, `docs/runbooks/billing-state.md`) and
a dev Postgres holding the migrated ledger schema, so `task check` holds only the offline gates
that stay green without either; a human runs this script attended (WORKFLOW.md `live_execution`),
this PR's review is the approval it needs, and its output — subject keys, states, counts, wall
clock timings — is the receipt for task 4.1.

The script seeds its own controlled scenario for every check rather than relying on ambient mart
data: v1 mart rows are a manually adjudicated seed (proposal.md open question 2) and are not
guaranteed to carry every case this task needs to prove. Four checks, in order:

1.  A synthetic `billing_episode` is opened at `open` (task 4.0: `open_billing_episode` lands
    state-bearing there) and a positive `billing_eligibility` mart row is declared for it. After
    `run_relay`, `state_of_record` for the episode is `qualified`, and the batch's
    `RunReceipt.transitioned == 1`. There is no separate patient-state-bus read surface in this
    repo, so `transitioned` is the closest available proxy for "the transition landed on the
    bus" — it proves the paired `declare_transition` committed, not the broadcast itself (see the
    inline comment at the assertion).
2.  A positive `coverage_eligibility` mart row is declared for a fresh, never-opened
    `(patient, payer)` pair. After `run_relay`, `state_of_record` for the coverage subject is
    `verified_active` with no separate genesis event — the mint-on-first-declare rule
    (`docs/runbooks/billing-state.md` #Pairing semantics).
3.  An immediate second `run_relay` against the same reader/declarer (same persisted cursor and
    watermarks) declares and transitions nothing — the replay-safety property.
4.  The check-1 episode is driven from `qualified` to `reported` directly through
    `PulseCoreClient.submit_command`, then one more positive `billing_eligibility` row is
    declared against it. The verdict itself still commits (declared, since it is a fresh row),
    but the paired transition is rejected — `reported → qualified` is not a legal edge — so the
    batch's `transition_rejected == 1` and the episode's `state_of_record` is unchanged.

**A cursor-ordering assumption this script leans on.** The relay's mart reader pages on
`computed_at`, one high-water mark for the whole table, persisted server-side per writer id
(`LedgerCursorStore`). Every row this script seeds is stamped with the wall clock at the moment of
insertion, which only becomes visible to the next `run_relay` call if it sorts after whatever the
persisted cursor already holds — true against a dev mart whose v1 seed rows are a one-time
adjudicated backfill rather than a live stream, but not a general guarantee. If a check's `declared`
count comes back short, the mart likely already holds rows timestamped ahead of "now" and the
persisted cursor needs resetting before rerunning.

**PHI posture.** Every subject key, patient key, and payer value this script constructs is an
obviously synthetic string (`demo4-...`, `SYNTH-PAYER-DEMO4`) — never a real identifier — and the
coverage subject id is derived through the same `sha256`-truncation convention the mart's real
producer uses, so the raw payer string never appears in a subject id either. `_print_receipt`
prints only subject keys (already synthetic), states, counts, and wall-clock timings — never an
outcome, a rule version, or any other verdict payload value.

Configuration (never printed): every `VERDICT_RELAY_*` variable `verdict_relay.production`
resolves (`resolve_production_config`) — the pulse-core base URL and token, and the Snowflake
account/user/credential/warehouse/database/schema/table — must already be set in the calling
environment, exactly as `task relay:run TARGET=dev` expects them (`docs/runbooks/billing-state.md`
#Poll cadence). Unlike Twenty's `PULSE_TWENTY_<TARGET>_*` pair, these variable names carry no
target segment (Taskfile.yml `relay:run`), so `--target` below labels the receipt only — it
confirms which environment the operator meant to point their already-exported variables at, it
does not select which variables are read.

Usage:
    scripts/demo/demo4_billing_declare_back.py [--target dev] [--database-url URL]
    scripts/demo/demo4_billing_declare_back.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from pulse_core.client import PulseCoreClient
from pulse_core.generated import DeclareTransitionCommand, OpenBillingEpisodeCommand
from pulse_ledger.reads import state_of_record
from verdict_relay.config import SUBJECT_TYPE_BY_VERDICT, TRANSITION_BY_OUTCOME
from verdict_relay.declarer import Declarer
from verdict_relay.mart_reader import MartReader
from verdict_relay.production import (
    ConflictingProductionVariablesError,
    MissingProductionVariableError,
    ProductionConfig,
    _snowflake_connect,
    build_production_dependencies,
    resolve_production_config,
)
from verdict_relay.run import run_relay

#: demo1's own local dev default (`packages/ocean/infra/docker-compose.yml`'s `ledger-postgres`) —
#: lets this script smoke-test offline before pointing `--database-url` at dev.
DEFAULT_DATABASE_URL = (
    f"postgresql://ledger:{os.environ.get('LEDGER_POSTGRES_PASSWORD', 'changeme')}@localhost:5434/ledger"
)

#: An obviously-synthetic payer string — never a real payer name (PHI posture above).
SYNTHETIC_PAYER = "SYNTH-PAYER-DEMO4"

#: A synthetic rule_version distinct from the real `manual-*-v1` convention (proposal.md open
#: question 4), so a receipt can never be mistaken for a real Billy-adjudicated row.
SYNTHETIC_RULE_VERSION = "demo4-synthetic-v1"

BILLING_EPISODE_SUBJECT_TYPE = "billing_episode"
COVERAGE_SUBJECT_TYPE = "coverage"


class DemoAssertionError(AssertionError):
    """One of Demo 4's four live assertions failed. The script exits nonzero when this is raised."""


def _check(condition: object, message: str) -> None:
    if not condition:
        raise DemoAssertionError(message)


def _print_receipt(step: str, body: Mapping[str, Any]) -> None:
    print(json.dumps({"step": step, **body}, default=str))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--target",
        choices=("dev", "staging", "prod"),
        default="dev",
        help="which environment this run is against, for the receipt only — VERDICT_RELAY_* "
        "variable names carry no target segment (module docstring), so this never changes which "
        "credentials are read.",
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="ledger Postgres DSN, a plain postgresql:// URI (psycopg, not SQLAlchemy) — point "
        "this at dev once the local smoke-test passes",
    )
    return parser


def _coverage_subject_id(patient_subject_key: str, payer: str) -> str:
    """The coverage subject-key convention (`docs/contracts/consumes.md` §Verdict mart):
    `{patient_subject_key}:{first 16 hex of sha256(payer, lowercased utf-8)}`. The raw payer
    string is hashed and truncated immediately, the same discipline the mart's real producer
    uses, so it never reaches a subject id, a log line, or this script's own receipts."""
    digest = hashlib.sha256(payer.lower().encode("utf-8")).hexdigest()
    return f"{patient_subject_key}:{digest[:16]}"


def _seed_mart_row(
    config: ProductionConfig,
    *,
    subject_id: str,
    verdict_type: str,
    outcome: str,
    rule_version: str,
    as_of: datetime,
    lineage_ref: str,
    computed_at: datetime,
    reason: str | None = None,
) -> None:
    """Insert exactly one synthetic row into the verdict mart — the eight pinned columns
    (`docs/contracts/consumes.md` §Verdict mart), nothing else.

    Reuses `verdict_relay.production._snowflake_connect` rather than re-deriving its
    account/user/credential/warehouse/database/schema resolution and password/key-pair branching
    a second time: it is already the reviewed, lazily-imported connect path (mirrors
    `pulse_core.catalog_release_cli._snowflake_connect`'s own posture), so calling it here means
    this script's write path and the production `SnowflakeRowSource`'s read path can never drift
    apart, and `snowflake.connector` is still never imported until this function actually runs.
    """
    connection = _snowflake_connect(config)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"INSERT INTO {config.snowflake_table} "  # noqa: S608 - table name from resolved config, not user input
                "(subject_id, verdict_type, outcome, reason, rule_version, as_of, lineage_ref, computed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    subject_id,
                    verdict_type,
                    outcome,
                    reason,
                    rule_version,
                    as_of.isoformat(),
                    lineage_ref,
                    computed_at.isoformat(),
                ),
            )
            connection.commit()
        finally:
            cursor.close()
    finally:
        connection.close()


# --- The four assertions ---------------------------------------------------------------------


def step_billing_declare_back(
    conn: psycopg.Connection,
    client: PulseCoreClient,
    reader: MartReader,
    declarer: Declarer,
    config: ProductionConfig,
) -> str:
    """1/4 (task 4.1 check a): a positive billing_eligibility verdict qualifies its episode."""
    subject_key = f"demo4-billing-{uuid.uuid4()}"
    now = datetime.now(tz=UTC)
    month = date.today().replace(day=1)

    open_response = client.submit_command(
        OpenBillingEpisodeCommand(subject_key=subject_key, month=month), effective_at=now
    )
    _check(
        open_response.is_success,
        f"open_billing_episode for {subject_key} did not commit: {open_response.classification}",
    )

    _seed_mart_row(
        config,
        subject_id=subject_key,
        verdict_type="billing_eligibility",
        outcome="positive",
        rule_version=SYNTHETIC_RULE_VERSION,
        as_of=now,
        lineage_ref=f"demo4-lineage-{uuid.uuid4()}",
        computed_at=now,
    )

    receipt = run_relay(reader, declarer)
    # `transitioned` is the closest available proxy in this repo for "the transition landed on
    # the patient-state bus" — there is no separate bus-read surface here, so this asserts the
    # paired `declare_transition` committed, not the broadcast itself (module docstring, check 1).
    _check(receipt.transitioned == 1, f"expected exactly one transitioned in this batch, got {receipt.transitioned}")

    state = state_of_record(conn, BILLING_EPISODE_SUBJECT_TYPE, subject_key)
    _check(state == "qualified", f"expected billing_episode {subject_key} at 'qualified', got {state!r}")

    _print_receipt(
        "billing_declare_back",
        {
            "subject_key": subject_key,
            "state": state,
            "declared": receipt.declared,
            "transitioned": receipt.transitioned,
        },
    )
    return subject_key


def step_coverage_mint_and_transition(
    conn: psycopg.Connection,
    reader: MartReader,
    declarer: Declarer,
    config: ProductionConfig,
) -> str:
    """2/4 (task 4.1 check b): a positive coverage_eligibility verdict mints and transitions a
    fresh, never-opened (patient, payer) pair — no separate genesis event is written."""
    patient_subject_key = f"demo4-patient-{uuid.uuid4().hex[:16]}"
    subject_id = _coverage_subject_id(patient_subject_key, SYNTHETIC_PAYER)
    now = datetime.now(tz=UTC)

    before = state_of_record(conn, COVERAGE_SUBJECT_TYPE, subject_id)
    _check(before is None, f"coverage subject {subject_id} already has a state before its first declare")

    _seed_mart_row(
        config,
        subject_id=subject_id,
        verdict_type="coverage_eligibility",
        outcome="positive",
        rule_version=SYNTHETIC_RULE_VERSION,
        as_of=now,
        lineage_ref=f"demo4-lineage-{uuid.uuid4()}",
        computed_at=now,
    )

    receipt = run_relay(reader, declarer)
    _check(receipt.transitioned == 1, f"expected exactly one transitioned in this batch, got {receipt.transitioned}")

    state = state_of_record(conn, COVERAGE_SUBJECT_TYPE, subject_id)
    _check(state == "verified_active", f"expected coverage {subject_id} at 'verified_active', got {state!r}")

    _print_receipt(
        "coverage_mint_and_transition",
        {"subject_id": subject_id, "state": state, "declared": receipt.declared, "transitioned": receipt.transitioned},
    )
    return subject_id


def step_immediate_rerun_is_noop(reader: MartReader, declarer: Declarer) -> None:
    """3/4 (task 4.1 check c): an immediate rerun against the same cursor state changes nothing."""
    receipt = run_relay(reader, declarer)
    _check(receipt.declared == 0, f"expected zero newly-declared rows on the immediate rerun, got {receipt.declared}")
    _check(receipt.transitioned == 0, f"expected zero transitions on the immediate rerun, got {receipt.transitioned}")
    _print_receipt(
        "immediate_rerun",
        {
            "declared": receipt.declared,
            "replayed": receipt.replayed,
            "skipped_stale": receipt.skipped_stale,
            "transitioned": receipt.transitioned,
        },
    )


def step_reported_transition_rejected(
    conn: psycopg.Connection,
    client: PulseCoreClient,
    reader: MartReader,
    declarer: Declarer,
    config: ProductionConfig,
    billing_subject_key: str,
) -> None:
    """4/4 (task 4.1 check d): a verdict against a reported episode keeps the verdict, drops the
    transition, and leaves `state_of_record` unchanged."""
    now = datetime.now(tz=UTC)

    transition_response = client.submit_command(
        DeclareTransitionCommand(
            subject_key=billing_subject_key,
            subject_type=BILLING_EPISODE_SUBJECT_TYPE,
            to_state="reported",
            reason="demo4 declare-back: drive qualified -> reported ahead of the rejection check",
        ),
        effective_at=now,
    )
    _check(
        transition_response.is_success,
        f"declare_transition to 'reported' for {billing_subject_key} did not commit: {transition_response.classification}",
    )
    state_before = state_of_record(conn, BILLING_EPISODE_SUBJECT_TYPE, billing_subject_key)
    _check(
        state_before == "reported",
        f"expected billing_episode {billing_subject_key} at 'reported' before the rejection check, got {state_before!r}",
    )

    _seed_mart_row(
        config,
        subject_id=billing_subject_key,
        verdict_type="billing_eligibility",
        outcome="positive",
        rule_version=SYNTHETIC_RULE_VERSION,
        as_of=now,
        lineage_ref=f"demo4-lineage-{uuid.uuid4()}",
        computed_at=now,
    )

    receipt = run_relay(reader, declarer)
    _check(
        receipt.transition_rejected == 1,
        f"expected exactly one transition_rejected, got {receipt.transition_rejected}",
    )
    _check(
        receipt.declared + receipt.replayed == 1,
        f"expected the verdict itself to still commit (declared or replayed), got "
        f"declared={receipt.declared} replayed={receipt.replayed}",
    )

    state_after = state_of_record(conn, BILLING_EPISODE_SUBJECT_TYPE, billing_subject_key)
    _check(state_after == "reported", f"state of record changed on a rejected transition: {state_after!r}")

    _print_receipt(
        "reported_transition_rejected",
        {
            "subject_key": billing_subject_key,
            "state": state_after,
            "declared": receipt.declared,
            "replayed": receipt.replayed,
            "transition_rejected": receipt.transition_rejected,
        },
    )


# --- Entry point --------------------------------------------------------------------------------


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    environment = os.environ if env is None else env

    print(f"=== Demo 4: live declare-back on dev (task 4.1, target={args.target}) ===")
    try:
        config = resolve_production_config(environment)
    except (MissingProductionVariableError, ConflictingProductionVariablesError) as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1

    row_source, cursor_store, client = build_production_dependencies(config)
    reader = MartReader(row_source, cursor_store)
    declarer = Declarer(
        client,
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        transition_by_outcome=TRANSITION_BY_OUTCOME,
        watermarks=reader.watermarks,
    )

    try:
        with psycopg.connect(args.database_url, autocommit=True) as conn:
            print("\n[1/4] a positive billing_eligibility verdict qualifies a fresh episode")
            billing_subject_key = step_billing_declare_back(conn, client, reader, declarer, config)

            print("\n[2/4] a positive coverage_eligibility verdict mints and transitions an unseen subject")
            step_coverage_mint_and_transition(conn, reader, declarer, config)

            print("\n[3/4] an immediate rerun changes nothing")
            step_immediate_rerun_is_noop(reader, declarer)

            print("\n[4/4] a verdict against a reported episode counts transition_rejected, not the verdict")
            step_reported_transition_rejected(conn, client, reader, declarer, config, billing_subject_key)
    except DemoAssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        row_source.close()
        cursor_store.close()
        client.close()

    print("\n=== Demo 4: all four live assertions passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
