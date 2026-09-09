# ADR-0006: Warehouse Modeling Ownership Splits by Producer

- **Status**: Accepted
- **Date**: 2026-09-08

## Context

Two teams write SQL against the same warehouse, and nothing on record said which one owns which
object. `packages/ocean` already ships committed SQL for `STG_EVENTS`
(`packages/ocean/infra/snowflake/stg_events_events.sql`) — a deliberate rejection of dbt for that
view, decided in `snowflake-projection` design decision 3, because the view IS the publisher
contract other repos consume and it must version with this repo, not with a dbt estate that has
no publisher contract owner. Meanwhile `brookai/data-platform`'s dbt project computes the verdict
marts pulse reads (`docs/contracts/consumes.md`, the "Verdict mart" entry) — business logic pulse
does not hold and should not fork. `docs/contracts/publishes.md` and `consumes.md` had accumulated
rows on both sides of this line with no rule connecting them, so a new surface's home was a guess
each time.

## Decision

**We will split warehouse modeling ownership by producer, not by warehouse.** pulse owns and
commits SQL over the surfaces pulse itself produces — `STG_EVENTS`, reconciliation views, and data
quality views derived from the event landing pulse writes. That SQL lives in this repo, reviewed
and versioned the same way `STG_EVENTS` already is (precedent: `snowflake-projection` design
decision 3). data-platform owns SQL that computes business logic from pulse's published facts —
the verdict marts and anything else that derives a business decision rather than reshaping pulse's
own landing. Every row in `publishes.md` and `consumes.md` states which side of this rule it is on.

## Consequences

- A new warehouse surface has one deterministic home: if pulse produced the underlying facts and
  the object reshapes or checks them, it is committed SQL in this repo; if the object encodes
  business rules over facts pulse merely supplies, it is data-platform's dbt project.
- `publishes.md` and `consumes.md` each carry a pointer sentence to this ADR in their preambles, so
  a reader lands on the rule before reading any row.
- Cost: two SQL estates to keep aligned at the seam — a pulse-side schema change that a
  data-platform mart depends on is a cross-repo coordination, not a same-PR fix. The existing
  `consumes.md`/`publishes.md` discipline (register a row, name the breakage risk) is the
  mitigation, not a new mechanism.
- This does not reopen `snowflake-projection` decision 3 or the cpt-om/billing-engine ownership
  split (`producer-registry.md`); it generalizes the same reasoning those already applied.

## Alternatives considered

- **One warehouse SQL estate, either all dbt or all committed SQL**: rejected — forcing
  `STG_EVENTS` into dbt would put pulse's own publisher contract under a project pulse does not
  control the release cadence of; forcing the verdict marts into this repo would put business
  rules pulse does not own into pulse's review surface, duplicating logic that already has a home.
- **Ownership by warehouse database/schema instead of by producer**: rejected — schema boundaries
  in Snowflake do not track who authored the logic, and a rule stated that way would drift the
  first time an object moved schemas without changing owners.
- **No stated rule, decide per-surface as they arise**: rejected — this is the status quo that
  prompted the ADR; it produces exactly the ambiguity this decision closes.

---

**The log is append-only.** A decision that no longer holds gets a new ADR and a status flip on
the old one — never an edit. The point is the history, not the current state; the current state
is the code.
