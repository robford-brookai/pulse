"""Connector kit — the shared primitives every pulse connector stands on.

Extracted from the shipped integrations (consent-ingress, verdict-relay, twenty-projection),
never invented: a primitive lands here only by refactoring a working copy out of a donor
(connector-kit spec). Today the package holds the inbound read contract
(`pulse_core.connector.rows`) and the outbound consume loop (`pulse_core.connector.consume`);
the declare pipeline joins it as it is extracted.
"""

from pulse_core.connector.consume import (
    ConsumeReport,
    ConsumerHandler,
    Deduper,
    InMemoryDeduper,
    Sleeper,
    consume,
    consume_once,
    is_watermark_stale,
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
    "ConsumeReport",
    "ConsumerHandler",
    "CursorStore",
    "Deduper",
    "FixtureRowSource",
    "InMemoryDeduper",
    "LedgerCursorStore",
    "RowError",
    "RowSource",
    "RowValidationError",
    "Sleeper",
    "ValidatedPage",
    "consume",
    "consume_once",
    "is_watermark_stale",
    "parse_instant",
    "required_string",
    "required_timestamp",
    "submit_with_retry",
    "validate_page",
]
