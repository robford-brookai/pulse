"""PULSE Customer.io consent ingress.

D9's forward consent ingress: declares the delivered `streamline.cio_raw`/`cio_prod` Snowflake
landing as attributed, provenance-carrying `record_communication_consent` commands on the
ledger's single write path — the recording half of the consent story whose correcting half is
`consent-reconciliation`'s sweep (`schedules.consent_sweep`).

Submits through `pulse_core.client.PulseCoreClient` — no direct ledger writes, and no dependency
on `pulse-ledger` or `schedules` (the `{subject_key}:{channel}` grain composition is duplicated
from the sweep, not imported — design decision 3). This module carries no logic itself; wave 1
(tasks 2.x, 3.x) fills in `row_source.py` and `declarer.py`.
"""

from __future__ import annotations
