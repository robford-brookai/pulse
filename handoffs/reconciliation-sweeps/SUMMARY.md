# Handoff Summary: reconciliation-sweeps

Collected 3 handoff(s).

## reconciliation-sweeps-task-006

## Spec Updates

None. Implementation matches `specs/reconciliation-sweeps/spec.md` and design.md decision 8
as written — no drift found.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None.

## New Scenarios

None.

## reconciliation-sweeps-task-008

## Spec Updates

None — this task is itself the doc-updater pass for the change: `docs/contracts/publishes.md`,
`docs/contracts/consumes.md`, `design/delivery/pulse-program-roadmap.md`, and
`docs/runbooks/reconciliation-sweeps.md` are edited directly (none of these are `openspec/specs/`
files), per the task's own instruction. No `openspec/` file was touched.

### Added Requirements

None.

### Modified Requirements

None.

### Removed Requirements

None.

## Design Drift

None found. Prior tasks (1.2, 2.1, 3.1, 3.2) each noted a "proposed publishes.md row written to
HANDOFF.md" in their commit messages, but no `handoffs/reconciliation-sweeps/` directory exists
yet (nothing has been collected for this change), and each of those worktrees' own `HANDOFF.md` is
untracked and gone with the worktree. This task re-derived the correct `publishes.md`/`consumes.md`
content directly from the shipped code (`subject_current_state.sql`, `receipt.py`,
`sweep_registry.py`, `consumer_registry.py`, `cli.py`) and design.md decisions 3, 5, 6, 7 rather
than from those lost proposals — a future `task collect` for this change will find nothing to fold
in from tasks 1.2/2.1/3.1/3.2 on the docs front.

## New Scenarios

None.

## reconciliation-sweeps-task-3-4

### Added Requirements

Spec: `openspec/changes/reconciliation-sweeps/specs/reconciliation-sweeps/spec.md`

> ### Requirement: A consumer whose source this environment does not host is named, not faked
> A `projection_conformance` sweep SHALL resolve every environment variable its consumers' sources
> need before opening any connection, and SHALL fail startup naming the first required variable that
> is unset. A consumer registered for the family whose source group is absent from the environment
> entirely SHALL be reported in the receipt as `unconfigured` and skipped: it SHALL NOT count as a
> divergence of any kind, SHALL NOT make the family `no_consumers`, and SHALL NOT prevent the
> family's other consumers from comparing. A source group that is only partly configured SHALL fail
> startup by name rather than be reported `unconfigured`.
>
> #### Scenario: A missing variable fails startup by name
> - **GIVEN** a required variable for the sweep's ledger read is unset
> - **WHEN** the sweep starts
> - **THEN** it fails naming that variable, before any source is connected, and names no value
>
> #### Scenario: An environment without the graph database still sweeps enrollment
> - **GIVEN** an environment that hosts no OCEAN graph database
> - **WHEN** the `enrollment` sweep runs
> - **THEN** `graph-projection-patients` is reported `unconfigured`, `twenty-board` and
>   `warehouse-landing` compare their rows, and the receipt is not `no_consumers`
>
> #### Scenario: A half-configured source is a fault, not an absence
> - **GIVEN** a source group with some but not all of its variables set
> - **WHEN** the sweep starts
> - **THEN** it fails naming the missing variable rather than skipping that consumer

### Modified Requirements

Spec: `.../specs/reconciliation-sweeps/spec.md`, requirement **"Sweeps run on a schedule and every
run ends in a receipt"** — the receipt's per-consumer shape (design.md decision 7) gains one field:
`unconfigured` (boolean, default false), true for a registered consumer whose source this
environment does not host. Every other per-consumer field is zero on such an entry, so the receipt
still accounts for every registered consumer of the family without inventing a count no row backs.

Design doc: `design.md` decision 7's receipt list should name `unconfigured` alongside `uncitable`,
`in_flight`, `malformed`, `pre_floor`.

### Removed Requirements

None.

## Design Drift

None. Decision 11's text and this implementation agree. Two facts the design does not state, both
forced by the wiring and worth recording where the design is read:

- **The board is compared in the ledger's vocabulary, not Twenty's.** The projection stores a
  catalog state as `encode_option_value(state)` (UPPER_SNAKE); the ledger's fold carries the catalog
  vocabulary itself. The board read is translated back through the catalog's own state set for the
  family before comparison — comparing the two forms verbatim would report every board row as
  `state` drift. `encode_option_value` is not injective, so the translation is a lookup over the
  catalog, never a lowercasing.
- **The subject universe is the union of the consumers' rows.** The command API exposes no bulk
  ledger enumeration (decision 2 keeps the sweep off any direct ledger connection), so the snapshot
  is pinned per subject over the keys the consumers returned. A subject the ledger holds that no
  consumer projects at all is therefore not visible to this sweep.

## New Scenarios

Covered by the Added Requirements above.

## Doc-Updater Instructions

1. For each spec-relevant update inlined above, edit the corresponding file in:
   `openspec/changes/reconciliation-sweeps/specs/`
2. Run `openspec validate reconciliation-sweeps` to check format.
3. Run `openlore drift` to check for new drift.
4. Ignore implementation details — only apply plan-relevant changes.
5. A `## Design Drift` section above means flag for human review.
