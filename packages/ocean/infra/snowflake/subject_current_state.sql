-- STG_EVENTS.SUBJECT_CURRENT_STATE — the warehouse's own fold of the ledger's landing, one row
-- per subject.
--
-- Pulse-committed SQL, not dbt (design.md decision 3, ADR-0006): this view reshapes a surface
-- pulse itself produces (STG_EVENTS.EVENTS), so it lives and versions in this repo beside
-- stg_events_events.sql, applied idempotently by `task snowflake:subject-current-state`
-- (CREATE OR REPLACE makes a re-run a no-op on an unchanged file).
--
-- Fold rule: latest landed event per `(subject_type, subject_key)` by `seq` — the ledger's own
-- commit order, never `effective_at`/`recorded_at` — wins. This is deliberately simpler than
-- `pulse_ledger.fold.fold_state`'s bitemporal, reversal-aware rule (design.md decision 3's
-- literal text pins "latest landed event ... by seq"); a reversal or its target is not filtered
-- out before this fold picks a winner. `state` is `payload:to_state` off that winning row, `NULL`
-- when the winner carries none (a reversal-only event, or any other non-state-bearing event) —
-- the reconciliation sweep (`projection-conformance` spec) reads that as a `state` divergence
-- against the ledger's own fold, same as any other disagreement, rather than this view silently
-- reaching past the winner for a state-bearing predecessor.
--
-- Floor: bounded below by the STG_EVENTS `min_complete_from` watermark
-- (docs/contracts/publishes.md, pinned `2026-08-26` at feed revival) on `_loaded_at` — the
-- landing's own completeness cutoff, not the event's `effective_at`. A subject whose entire
-- history landed before the floor is not filtered to a partial fold here; it is absent from this
-- view altogether, which the sweep counts as `pre_floor` (design.md decision 5) rather than a
-- warehouse divergence.
CREATE OR REPLACE VIEW STREAMLINE.STG_EVENTS.SUBJECT_CURRENT_STATE AS
SELECT
    subject_type,
    subject_key,
    seq,
    payload:to_state::VARCHAR AS state,
    event_id,
    event_type,
    effective_at,
    occurred_at,
    recorded_at,
    _loaded_at
FROM STREAMLINE.STG_EVENTS.EVENTS
WHERE _loaded_at >= '2026-08-26'
QUALIFY ROW_NUMBER() OVER (PARTITION BY subject_type, subject_key ORDER BY seq DESC) = 1
;
