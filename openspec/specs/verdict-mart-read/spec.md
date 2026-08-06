# verdict-mart-read Specification

## Purpose
Defines how the verdict relay reads the warehouse verdict mart: the pinned row contract, the
declaration order, and the durable cursor that makes a batch run resumable after a crash.
## Requirements
### Requirement: Mart rows are read in declaration order

The relay SHALL read the verdict mart contract — one row per (subject, verdict_type, run), columns
`subject_id, verdict_type, outcome, reason, rule_version, as_of, lineage_ref, computed_at` — and
yield rows ordered by (subject, `as_of`), so the declarer receives each subject's verdicts oldest
first. A row that does not satisfy the contract (missing column, unparseable timestamp) SHALL fail
the run before any declaration, naming the offending row.

#### Scenario: A batch yields subject-grouped, as_of-ordered rows

- **GIVEN** mart rows for subjects A and B with interleaved `as_of` values
- **WHEN** the reader yields a batch
- **THEN** rows arrive grouped by subject and ascending by `as_of` within each subject, and every
  contract column is present on every row

### Requirement: Runs are resumable via a durable cursor

The reader SHALL page on `computed_at` and persist its position through the ledger's writer-state
facility under the relay's own writer id, with JSON-native cursor values. After a crash, a
restarted run SHALL resume from the persisted cursor without re-reading completed pages;
idempotency makes any overlap at the boundary a replay, never a second declaration.

#### Scenario: Crash and resume without re-reading

- **GIVEN** a run that persisted its cursor after page N and then crashed
- **WHEN** a new run starts
- **THEN** it reads the persisted cursor and continues from page N+1, re-reading no completed
  page, and any boundary overlap classifies as a replay downstream
