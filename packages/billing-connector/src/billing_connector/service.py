"""Service entry point — wires config, store, client, and the kit's consume loop (task 2.3,
design.md decision 6).

This module is the connector's only process and its only decision about *when* to evaluate.
`run_batch` is the consume handler: `pulse_core.connector.consume_once` calls it once per
delivered event (despite the name — "batch" names one consume pass over whatever the queue
delivered, never a scheduled batch job, spec: "Evaluation is event-driven, never batch-gated").
It folds the event into `store`, calls `evaluate.evaluate_subject` for the affected subject,
declares each resulting `Evaluation` through `declare.declare_pair`, records the declared event
id back on the engine's `evaluations` row, and returns the receipt this event's handling
contributes. `main` resolves `Config.from_env()`, refuses to start on a registry mismatch (spec:
"A registry mismatch halts startup"), and drives the consume loop — `sys.argv` is `argv`'s
caller, never read directly here, so tests can call `main` with a fixed list.

**The trigger set is a closed allowlist.** `TRIGGER_SUBJECT_TYPES` is the whole of it:
`billing_episode` and `coverage`, per design.md decision 4 as amended 2026-09-02. Every other
subject type the queue delivers — `consent` and `enrollment` above all, but equally anything a
future rule broadening lets through — folds into facts, evaluates nothing, and counts `deferred`.
An allowlist rather than a `{consent, enrollment}` denylist because the failure modes are not
symmetric: a subject type missing from a denylist would trigger a billing verdict nobody
designed, continuously, whereas a subject type missing from this allowlist is a `deferred` count
sitting visibly in every receipt line until someone widens it. The fan-out those deferrals wait
on is a catalog fact that does not exist yet; the proposal for it is in `HANDOFF.md`.

**The engine's database is the engine's own credential, not this connector's.** `Config` holds
exactly one credential name — this connector's ledger writer token (spec: "One credential, names
in config, values from the environment") — and no database connection string of any kind. The
`billing_engine` database `evaluate_subject` reads facts from is the *engine's* store, so `main`
resolves it through the engine's own name for its own credential (`billing.consumer`), which is
where that name is declared and reviewed. No second credential name is declared in this package.

`Receipt` accumulates per pass, not per event: `run` logs exactly one receipt line for each
`consume_once` pass (spec: "Every run ends in a counted receipt", "the receipt SHALL carry counts
and subject keys only" — the line carries counts alone) and one closing line for the run.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import time
from typing import TYPE_CHECKING, Any, cast

import psycopg
from billing.consumer import CREDENTIAL_ENV_VAR as ENGINE_DATABASE_ENV_VAR
from billing.store import PostgresFactStore
from pulse_core.client import PulseCoreClient
from pulse_core.connector import ConsumerHandler, Deduper, InMemoryDeduper, Sleeper, consume_once

from billing_connector.config import Config
from billing_connector.declare import declare_pair
from billing_connector.evaluate import Evaluation, SubjectRef, evaluate_subject, validate_registry
from billing_connector.receipts import Receipt

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import ModuleType

    from billing_connector.declare import DeclareResult

logger = logging.getLogger("billing_connector.service")

#: This connector's D15 writer identity — the credential the ledger resolves as
#: `billing-connector` (ADR-0003: attribution is authentication). A design-time constant, not
#: configuration: every deploy of this connector is this one writer (`verdict_relay.production`'s
#: `WRITER_ID` precedent).
WRITER_ID = "billing-connector"

#: The subject types whose events trigger evaluate → declare (design.md decision 4, as amended
#: 2026-09-02). A closed allowlist — see the module docstring for why the complement is not a
#: denylist. Widening this is a reviewed edit, same as the registry itself.
TRIGGER_SUBJECT_TYPES = frozenset({"billing_episode", "coverage"})

#: How long `run` waits after a consume pass raised before trying again — the same backoff the
#: kit's own `consume` applies, kept here because `run` drives `consume_once` per pass itself in
#: order to emit one receipt line per pass (see `run`).
ERROR_BACKOFF_SECONDS = 5.0


def resolve_registry() -> dict[str, ModuleType]:
    """The registered verdict type → rule module mapping, read from the engine's registry.

    Spec: "The connector evaluates the registered verdict types" — whatever
    `billing.rules.registry` lists, never a name or a count pinned here (design.md decision 3).
    A plain import, not `Config.verdict_types()`' dynamic one: that indirection exists so
    `config.py` typechecks against an install missing the registry module, and by the time this
    process runs, a missing registry is a startup failure either way.
    """
    from billing.rules.registry import VERDICT_TYPES

    return dict(VERDICT_TYPES)


def run_batch(
    store: PostgresFactStore,
    config: Config,
    client: PulseCoreClient,
    envelope: Mapping[str, object],
    *,
    registry: dict[str, ModuleType] | None = None,
) -> Receipt:
    """Handle one delivered event: fold it, evaluate the affected subject, declare every
    resulting verdict, and return the receipt this event's handling contributes.

    Spec: "A fact arrives, a verdict follows" (an episode or coverage event evaluates and
    declares without waiting for a schedule); "Consent and enrollment fan-out wait for their
    fact" (an event whose subject type is not in `TRIGGER_SUBJECT_TYPES` — no catalog link to an
    episode subject exists for one — folds into facts, evaluates nothing, and counts as
    `deferred`); "Every run ends in a counted receipt" (the return value).

    Three dispositions, in this order:

    1. **The fold found nothing new** (`apply_event` is `False`: an event id this subject already
       recorded, or a fact older than what is folded). Nothing to evaluate, nothing deferred —
       an all-zero receipt. This is what makes a redelivered event evaluate exactly once even
       across a restart, where the kit's in-process dedupe has no memory of the first delivery.
    2. **A subject type outside the trigger set.** Folded, counted `deferred`, evaluated against
       nothing.
    3. **A triggering subject.** Evaluated, and every resulting `Evaluation` declared. `evaluated`
       counts the evaluations produced — one per registered verdict type that applies to this
       subject's type — so it lines up with `committed`/`replayed`/`rejected`, which are also
       per-declaration. A `coverage` event evaluates in full and produces none today, because the
       registry lists no coverage-subject verdict type; that is an `evaluated=0` pass, not a
       deferral, since nothing about it is waiting on a fact.

    `registry` defaults to `resolve_registry()`; a test injects one to exercise a registry other
    than the engine's shipped set. `store` is the engine's fact store — the same one the fold
    writes and `evaluate_subject` reads — so the connector holds one connection, not two.
    """
    applied = store.apply_event(envelope)
    subject_type = str(envelope["subject_type"])
    subject_key = str(envelope["subject_key"])

    if not applied:
        logger.info(
            "event %s for %s/%s contributed nothing new (redelivery or out of order); not evaluated",
            envelope.get("event_id"),
            subject_type,
            subject_key,
        )
        return Receipt()

    if subject_type not in TRIGGER_SUBJECT_TYPES:
        logger.info(
            "event %s folded for %s/%s and deferred: no catalog fact links this subject to the "
            "billing episodes it affects",
            envelope.get("event_id"),
            subject_type,
            subject_key,
        )
        return Receipt(deferred=1)

    evaluations = evaluate_subject(
        store,
        registry if registry is not None else resolve_registry(),
        config,
        SubjectRef(subject_type=subject_type, subject_key=subject_key),
    )

    receipt = Receipt(evaluated=len(evaluations))
    for evaluation in evaluations:
        result = declare_pair(client, evaluation)
        receipt = _count_declaration(receipt, result)
        _record_evaluation(store, evaluation, result)
    return receipt


def collecting_handler(
    store: PostgresFactStore,
    config: Config,
    client: PulseCoreClient,
    registry: dict[str, ModuleType],
    sink: list[Receipt],
) -> ConsumerHandler:
    """The kit's `ConsumerHandler` shape (`envelope -> None`) over `run_batch`, appending each
    event's receipt to `sink` — the kit's handler contract returns nothing, so the per-event
    receipts come back out of band, one list per consume pass.

    A factory rather than a closure written inside `run`'s loop: the handler must capture *this*
    pass's sink, and a function defined in a loop body capturing a loop-local is the shape that
    goes wrong the moment anything about the loop changes.
    """

    def handle(envelope: Mapping[str, object]) -> None:
        sink.append(run_batch(store, config, client, envelope, registry=registry))

    return handle


def run(
    config: Config,
    *,
    store: PostgresFactStore,
    client: PulseCoreClient,
    registry: dict[str, ModuleType],
    sqs_client: Any,
    deduper: Deduper | None = None,
    iterations: int | None = None,
    sleep: Sleeper = time.sleep,
) -> Receipt:
    """Consume the connector's queue — forever, or `iterations` passes for a bounded run —
    returning the run's total receipt.

    Spec: "Every run ends in a counted receipt". One receipt line per `consume_once` pass, and one
    closing line for the run: `consume_once` is the pass boundary the spec's "consume batch"
    names, and the kit's own `consume` offers no per-pass hook to log at (a kit gap noted in
    `HANDOFF.md`), so this drives the kit's public per-pass primitive directly rather than
    reimplementing any of its receive/handler/delete mechanics. A pass that raises is backed off
    exactly as `consume` backs it off, so a persistent outage does not spin the loop.

    Every seam a test needs is a parameter (`store`, `client`, `sqs_client`, `deduper`,
    `iterations`, `sleep`); `main` is what resolves the real ones.
    """
    active_deduper = deduper if deduper is not None else InMemoryDeduper()
    total = Receipt()

    count = 0
    while iterations is None or count < iterations:
        count += 1
        collected: list[Receipt] = []
        try:
            consume_once(
                collecting_handler(store, config, client, registry, collected),
                sqs_client=sqs_client,
                queue_url=config.queue_url,
                deduper=active_deduper,
            )
        except Exception:
            logger.exception("consume pass failed; backing off")
            sleep(ERROR_BACKOFF_SECONDS)
            continue

        pass_receipt = _total(collected)
        logger.info("%s", pass_receipt.format_line())
        total = _total([total, pass_receipt])

    logger.info("%s", total.format_line())
    return total


def main(argv: Sequence[str]) -> int:
    """Resolve configuration, verify the registry against the rule modules, and run the consume
    loop until told to stop.

    Spec: "Startup SHALL fail with the missing variable's name if any value is absent"
    (`Config.from_env()` raises `ConfigError` naming every missing or invalid variable at once —
    this function lets that exception surface as a nonzero exit, never catching and re-wrapping
    it, so the names reach the operator unaltered); "A registry mismatch halts startup" (`validate_registry` runs once
    here, before the first `consume_once` call, never per-event, and `RegistryMismatchError`
    surfaces the same way). Both checks run before any connection is opened, so a misconfigured
    deploy fails on its configuration rather than on a transport.

    `argv` is accepted so a test can call `main(["--iterations", "1"])` without touching
    `sys.argv`.
    """
    parser = argparse.ArgumentParser(
        prog="billing-connector",
        description="Declare billing verdicts on the ledger as the engine's facts change.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="stop after this many consume passes (default: run until stopped)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    config = Config.from_env()
    registry = resolve_registry()
    validate_registry(registry)

    logger.info("billing-connector starting: %d registered verdict type(s)", len(registry))
    conn = psycopg.connect(os.environ[ENGINE_DATABASE_ENV_VAR])
    try:
        with PulseCoreClient(
            config.ledger_base_url,
            writer_id=WRITER_ID,
            token=os.environ[config.credential_name],
        ) as client:
            run(
                config,
                store=PostgresFactStore(conn),
                client=client,
                registry=registry,
                sqs_client=_sqs_client(),
                iterations=cast("int | None", args.iterations),
            )
    finally:
        conn.close()
    return 0


def _sqs_client() -> Any:
    """The real SQS client, `boto3` imported here and nowhere else so importing this module never
    requires it installed — the same lazy shape the kit's own `consume` uses for its default.

    `boto3.client` is an overload set over every AWS service whose returns the installed stubs
    leave unresolved, which pyright strict reports as an unknown member type; the kit types its
    own `sqs_client` seam as `Any` for the same reason, so the ignore stops here rather than
    spreading a service-client type through the connector.
    """
    import boto3

    return cast("Any", boto3.client("sqs"))  # pyright: ignore[reportUnknownMemberType]


def _count_declaration(receipt: Receipt, result: DeclareResult) -> Receipt:
    """Fold one settled declaration into the running receipt — a new `Receipt`, never a mutation.

    `DeclareCounts.record` (the kit) owns the three-way classification count; its return type is
    the base class, but it is a `dataclasses.replace` of `self`, so the value is this `Receipt`
    subclass with its `evaluated`/`deferred` intact — hence the cast rather than a rebuild. A
    rejected paired transition then counts as a `rejected` of its own alongside the verdict's own
    disposition (spec: "A rejected transition keeps its evidence" — the verdict's commit and the
    transition's rejection are both true, so the receipt shows both).
    """
    counted = cast("Receipt", receipt.record(result.classification))
    if result.transition_rejected:
        counted = dataclasses.replace(counted, rejected=counted.rejected + 1)
    return counted


def _record_evaluation(store: PostgresFactStore, evaluation: Evaluation, result: DeclareResult) -> None:
    """Record one evaluation on the engine's `evaluations` row with its declared event id.

    Spec: "Each evaluation SHALL be recorded in the engine's `evaluations` store with the declared
    event id". A rejected verdict has no declared event id — nothing took effect, and the column
    is the table's own unique key — so there is no row to write; the rejection is in the receipt
    and in `declare.py`'s log line. A replayed verdict answers with the event id the original
    commit produced, so the insert conflicts onto the row already there and writes nothing new
    (`PostgresFactStore.record_evaluation`).
    """
    if result.event_id is None:
        return
    store.record_evaluation(
        subject_type=evaluation.subject.subject_type,
        subject_key=evaluation.subject.subject_key,
        verdict_type=evaluation.verdict_type,
        rule_version=evaluation.rule_version,
        outcome=evaluation.outcome,
        as_of=evaluation.as_of,
        declared_event_id=result.event_id,
    )


def _total(receipts: Sequence[Receipt]) -> Receipt:
    """The sum of several receipts, field by field — the pass total, and the run total from the
    pass totals. A new `Receipt` every time; nothing here mutates one."""
    return Receipt(
        committed=sum(receipt.committed for receipt in receipts),
        replayed=sum(receipt.replayed for receipt in receipts),
        rejected=sum(receipt.rejected for receipt in receipts),
        evaluated=sum(receipt.evaluated for receipt in receipts),
        deferred=sum(receipt.deferred for receipt in receipts),
    )


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main(sys.argv[1:]))
