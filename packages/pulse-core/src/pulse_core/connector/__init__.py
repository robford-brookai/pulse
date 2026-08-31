"""Connector kit — the shared primitives every pulse connector stands on.

Extracted from the shipped integrations (consent-ingress, verdict-relay, twenty-projection),
never invented: a primitive lands here only by refactoring a working copy out of a donor
(connector-kit spec). Today the package holds the inbound read contract
(`pulse_core.connector.rows`); the declare pipeline and the outbound consume loop join it as
they are extracted.
"""

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
    "DEFAULT_PAGE_SIZE",
    "CursorStore",
    "FixtureRowSource",
    "LedgerCursorStore",
    "RowError",
    "RowSource",
    "RowValidationError",
    "ValidatedPage",
    "parse_instant",
    "required_string",
    "required_timestamp",
    "validate_page",
]
