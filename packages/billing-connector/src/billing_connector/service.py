"""Service entry point — wires config, store, client, and the kit's consume loop (task 1.3 stub;
behavior fills in wave 1, design.md decision 6).

`run_batch` is the connector's consume handler: `pulse_core.connector.consume.consume` calls it
once per delivered event (despite the name — "batch" names one consume pass over whatever the
queue delivered, never a scheduled batch job, spec: "Evaluation is event-driven, never
batch-gated"). It folds the event into `store`, calls `evaluate.evaluate_subject` for the affected
subject, declares each resulting `Evaluation` through `declare.declare_pair`, and folds the result
into a running `receipts.Receipt`. `main` resolves `Config.from_env()`, refuses to start on a
registry mismatch (spec: "A registry mismatch halts startup"), and drives the consume loop —
`sys.argv` is `argv`'s caller, never read directly here, so tests can call `main` with a fixed
list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from billing_connector.config import Config
    from billing_connector.receipts import Receipt


def run_batch(
    store: object,
    config: Config,
    client: object,
    envelope: Mapping[str, object],
) -> Receipt:
    """Handle one delivered event: fold it, evaluate the affected subject, declare every
    resulting verdict, and return the receipt this event's handling contributes.

    Spec: "A fact arrives, a verdict follows" (an episode or coverage event evaluates and
    declares without waiting for a schedule); "Consent and enrollment fan-out wait for their
    fact" (an event with no catalog link to an episode subject folds into facts, evaluates
    nothing, and counts as `deferred`); "Every run ends in a counted receipt" (the return value).
    `store` and `client` are typed `object` for the same reason `evaluate.evaluate_subject`'s
    `store` parameter is: their concrete read/write surfaces for this call land at task 2.1/2.2.
    """
    raise NotImplementedError


def main(argv: Sequence[str]) -> int:
    """Resolve configuration, verify the registry against the rule modules, and run the consume
    loop until told to stop.

    Spec: "Startup SHALL fail with the missing variable's name if any value is absent"
    (`Config.from_env()` raises `MissingConfigVariableError` naming it — this function lets that
    exception surface as a nonzero exit, never catching and re-wrapping it); "A registry mismatch
    halts startup" (checked once here, before the first `consume` call, never per-event).
    `argv` is accepted so a test can call `main(["--flag"])` without touching `sys.argv` — this
    stub does not parse it yet.
    """
    raise NotImplementedError
