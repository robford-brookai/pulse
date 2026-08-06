"""PULSE clock-driven schedulers.

Two thin declarers, identical operational shape (proposal.md — What Changes):

- `month_open` — enumerates active/on-hold Enrollments through `pulse_ledger.reads.enumerate_state`
  and declares one `open_billing_episode` per enrollment x current month.
- `consent_sweep` — the D9 consent reconciliation sweep, diffing the delivered Customer.io
  suppression export against ledger CommunicationConsent current state.

Both submit through `pulse_core.client.PulseCoreClient` — no direct ledger writes. This module
carries no logic itself; wave 1 (tasks 2.x, 3.x) fills in `month_open.py` and `consent_sweep.py`.
"""

from __future__ import annotations
