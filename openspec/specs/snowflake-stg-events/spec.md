# snowflake-stg-events Specification

## Purpose
The STG_EVENTS ledger contract: the typed, deduplicated view of the ledger's event envelopes
that downstream warehouse consumers read instead of the raw landing — stated on the real
landing (`OCEAN_RAW.EVENTS`), with its completeness honestly bounded.
## Requirements
### Requirement: STG_EVENTS.EVENTS exposes the ledger envelope, one row per event

A committed view `STG_EVENTS.EVENTS` SHALL present one row per envelope `event_id` over the
raw landing, keeping the earliest arrival when duplicates exist, and SHALL type the envelope's
fields into columns. The pinned column list SHALL be derived from what the ledger's relay
actually emits — at minimum `event_id`, `event_type`, `subject_type`, `subject_key`, `seq`,
and `effective_at`, plus `_topic` and `_loaded_at` passthrough — never from the superseded v1
envelope document. The view SHALL NOT filter by topic; consumers filter on `_topic`.

#### Scenario: Duplicate arrivals collapse to one row

- **GIVEN** the same `event_id` present more than once in the raw landing
- **WHEN** STG_EVENTS.EVENTS is queried for it
- **THEN** exactly one row returns, the earliest-loaded arrival

#### Scenario: The columns match the emitter

- **GIVEN** the field set the relay's published envelope carries
- **WHEN** the view's column list is compared against it
- **THEN** every emitted envelope field has a typed column, and no column exists that the
  emitter does not produce (passthrough metadata columns excepted)

### Requirement: The contract is published with an explicit completeness watermark

`docs/contracts/publishes.md` SHALL carry the `STG_EVENTS.EVENTS` row: columns, grain, dedupe
rule, freshness query, and a `min_complete_from` date stamped at feed revival. The row SHALL
state that history before the watermark is incomplete until `projection-rebuild-drill` closes
the gap, so absence of pre-revival rows reads as documented, not as data loss.

#### Scenario: The published row bounds completeness

- **GIVEN** the publishes.md contract row
- **WHEN** a consumer reads it
- **THEN** it finds the pinned columns, the dedupe rule, the verbatim freshness query, a
  concrete `min_complete_from` date, and the named change that will close the earlier gap
