"""The live `CandidateLookup` adapter: the matcher (3.1) against the real ledger.

`LedgerLookup` is a thin pass-through over `pulse_ledger.identity.lookup_identifier` and
`find_candidates` — it computes nothing and decides nothing. The matcher's `_composite_tier`
already hashes the referral's demographics into a digest before it ever calls `find_candidates`
(`normalize.composite_digest`, task 2.1); this module never sees a demographic value, only the
digest the matcher hands it, so there is no code path here that could forward one to the ledger.

`InMemoryLookup` (3.1) and `LedgerLookup` are the same port viewed from two adapters — a test
double and the production one. Genesis brings its own adapter if it batches reads (design
decision 4 in `matcher.py`); this one is for the service entrypoint (task 4.3).
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from pulse_ledger import identity as ledger_identity

__all__ = ["LedgerLookup"]


class LedgerLookup:
    """`CandidateLookup` backed by one `psycopg.Connection` into the ledger.

    Holds the connection, nothing else — no cache, no session state across calls. Each method call
    is one read against `ledger.external_identifiers` or `ledger.person_match_keys`.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def lookup_identifier(self, system: str, value: str) -> str | None:
        """The person holding `(system, value)` exactly, or `None` — unwraps the ledger's binding."""
        binding = ledger_identity.lookup_identifier(self._conn, system=system, value=value)
        return None if binding is None else binding.person_key

    def find_candidates(self, match_key: str) -> Sequence[str]:
        """Persons indexed under this composite digest. `match_key` arrives pre-hashed; see above."""
        return ledger_identity.find_candidates(self._conn, match_key)
