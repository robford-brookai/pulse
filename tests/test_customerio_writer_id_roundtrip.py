"""The consent ingress's writer id round-trips through the command API's suffix mapping.

`customerio-consent-ingress` spec scenario "The writer id round-trips through the registry's
suffix mapping": a credential registered as `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO` must resolve,
via `pulse_ledger.auth._writer_id_from_suffix`, to exactly the writer id the ingress declares
under (`consent_ingress.declarer.CUSTOMERIO_WRITER_ID`). The id is spelled `customer-io`, not
`customer.io`, because the mapping only lowercases and turns `_` into `-` — no suffix can ever
produce a dot (`pulse-demo-closeout` design.md decision 9, issue #342).

This is the one place both packages are importable (same posture as `test_consent_grain_parity.py`):
neither package depends on the other at runtime, so the round-trip is proved here rather than
imported into either package's own test suite.

Offline: a pure function call, no network, no credentials.
"""

from __future__ import annotations

from consent_ingress.declarer import CUSTOMERIO_WRITER_ID
from pulse_ledger.auth import WRITER_TOKEN_PREFIX, _writer_id_from_suffix


def test_the_customerio_credential_suffix_resolves_to_the_ingress_writer_id():
    variable = f"{WRITER_TOKEN_PREFIX}CUSTOMER_IO"
    suffix = variable.removeprefix(WRITER_TOKEN_PREFIX)

    assert _writer_id_from_suffix(suffix) == CUSTOMERIO_WRITER_ID == "customer-io"
