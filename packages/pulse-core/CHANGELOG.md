# Changelog

All notable changes to `pulse-core` are recorded here, in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) style. Each entry that touches
`pulse_core.connector` carries a **Connector authors** line naming the concrete effect on a
connector build against the kit — read it before `uv sync` pulls in a new version.

This file starts with the devex-eight-2 audit (`.planning/reports/2026-09-02-devex-scorecard.md`,
"Upgrade Path" finding: no CHANGELOG, no deprecation machinery). Everything the kit shipped before
that audit is folded into the `0.1.0` entry below as its starting baseline; from here forward,
every kit change gets its own entry in the same PR that makes it.

## [Unreleased]

### Added
- This CHANGELOG. Connector authors: none — process only, no code changed.

## [0.1.0] — kit baseline

The connector kit as extracted from the three integrations it was proven against
(consent-ingress, verdict-relay, twenty-projection), per the connector-kit spec.

### Added
- `pulse_core.connector.rows` — the inbound read contract: `RowSource`, `CursorStore`,
  `FixtureRowSource`, `LedgerCursorStore`, page validation and row-level errors that name the
  offending row and column.
- `pulse_core.connector.declare` — the declare pipeline: idempotency-key derivation, response
  classification (`committed | replayed | rejected | transient`), retry with backoff on
  transient failures only (`submit_with_retry`), and `DeclareCounts` receipts.
- `pulse_core.connector.consume` — the outbound consume loop: `consume`, `consume_once`,
  event-id dedupe (`Deduper`, `InMemoryDeduper`), watermark staleness (`is_watermark_stale`).
- Connector authors: `from pulse_core.connector import <name>` is the supported surface for
  every name in `pulse_core.connector.__all__`; importing from the submodules directly works
  but is not covered by this changelog's compatibility notes.
