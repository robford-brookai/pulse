"""PULSE billing connector — the first connector built on the shared kit.

Turns the billing engine's folded facts into declared, attributed, versioned verdicts on the
ledger the moment the facts change, under one credential, with no warehouse on the write path
and no monetary value crossing its seam (spec: `billing-connector`). Scaffold only (task 1.1):
config, evaluation, declaration, the service entry, and receipts land in later waves.
"""

from __future__ import annotations

__version__ = "0.1.0"
