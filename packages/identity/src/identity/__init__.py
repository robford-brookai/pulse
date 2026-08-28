"""PULSE identity — the TIDE matcher v1 and its resolution service.

The `received -> resolved` Referral transition has no resolver: this package takes a received
Referral's demographics and source identifiers and decides which Person it is (proposal.md — Why).

Layering (design decision 1): a pure decision core — `normalize.py` (demographics to composite
match key digest) and `matcher.py` (the two-tier deterministic match) — with an effectful shell —
`resolver.py` (decisions to commands) and `service.py` (the consumption entrypoint). Wave 1
onward (tasks 2.x-5.x) fills in each module; this scaffold carries the package boundary and its
gates only.
"""

from __future__ import annotations
