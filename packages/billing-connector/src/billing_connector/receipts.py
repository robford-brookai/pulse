"""The connector's own counted receipt — the kit's three-count core plus this connector's two
additions (task 1.3, spec: "Every run ends in a counted receipt").

`Receipt` extends `pulse_core.connector.declare.DeclareCounts` (`committed`, `replayed`,
`rejected` — "the receipt's core", per that module's docstring) with `evaluated` and `deferred`:
every subject `evaluate.evaluate_subject` ran a rule for, and every event folded into facts but
evaluated against nothing because no catalog fact linked it to an episode subject (spec: "Consent
and enrollment fan-out wait for their fact"). `format_line` is the one piece of behavior this
scaffold task actually implements — the golden every later change's receipt output is pinned
against (`tests/test_receipts.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from pulse_core.connector import DeclareCounts


@dataclass(frozen=True)
class Receipt(DeclareCounts):
    """One run's full counted receipt: `committed`/`replayed`/`rejected` from the kit, plus this
    connector's `evaluated` and `deferred` (spec: "the receipt SHALL carry counts and subject
    keys only" — no field here is anything but a count)."""

    evaluated: int = 0
    deferred: int = 0

    def format_line(self) -> str:
        """The single machine-parsable receipt line: space-separated `key=value` pairs, kit
        counts first in `DeclareCounts` field order, then this connector's own two (spec: "The
        receipt shape is stable" — every run's line matches this shape byte for byte apart from
        the counts).

        `project=pulse` sits alongside `service=billing-connector` — the per-service tag Datadog
        APM keys on stays, and every pulse service also carries the shared tag monitors route on
        (design/delivery/pulse-runtime-readiness.md §1.5, decision 2026-09-08).
        """
        return (
            f"service=billing-connector project=pulse committed={self.committed} "
            f"replayed={self.replayed} rejected={self.rejected} evaluated={self.evaluated} "
            f"deferred={self.deferred}"
        )
