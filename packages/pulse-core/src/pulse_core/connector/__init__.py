"""Connector kit — the shared primitives every pulse connector stands on.

Extracted from the shipped integrations (consent-ingress, verdict-relay, twenty-projection),
never invented: a primitive lands here only by refactoring a working copy out of a donor
(connector-kit spec). Today the package holds the inbound read contract
(`pulse_core.connector.rows`) and the declare pipeline (`pulse_core.connector.declare`); the
outbound consume loop joins it as it is extracted.
"""

from pulse_core.connector.declare import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_DELAY_SECONDS,
    DeclareCounts,
    Jitter,
    Sleeper,
    TransientExhaustedError,
    backoff_delay,
    submit_with_retry,
)
from pulse_core.connector.rows import (
    DEFAULT_PAGE_SIZE,
    CursorStore,
    FixtureRowSource,
    LedgerCursorStore,
    RowError,
    RowSource,
    RowValidationError,
    ValidatedPage,
    parse_instant,
    required_string,
    required_timestamp,
    validate_page,
)

__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_DELAY_SECONDS",
    "DEFAULT_PAGE_SIZE",
    "CursorStore",
    "DeclareCounts",
    "FixtureRowSource",
    "Jitter",
    "LedgerCursorStore",
    "RowError",
    "RowSource",
    "RowValidationError",
    "Sleeper",
    "TransientExhaustedError",
    "ValidatedPage",
    "backoff_delay",
    "parse_instant",
    "required_string",
    "required_timestamp",
    "submit_with_retry",
    "validate_page",
]
