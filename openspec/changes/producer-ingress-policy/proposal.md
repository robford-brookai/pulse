# Proposal — producer-ingress-policy

## Why

The §4.4 producer policy (`design/migration/ocean-to-pulse-adaptation-plan.md`) is the migration's
sharp edge: an OCEAN producer whose event asserts a PULSE-subject state transition must stop
emitting and issue a command instead; only non-subject facts keep emitting directly. The
classification test is mechanical — does the schema name a state that lives in the catalog? —
but nothing checks it: today a producer schema in `packages/ocean` asserting `referral` state
would merge silently. `catalog-authority` archived 2026-08-07 and pinned the consumer contract
this gate needs (`docs/contracts/publishes.md`: `catalog/state_catalog.yaml` at repo head, semver
`catalog_version`, `pulse_core.generated`), so the gate is now buildable — and downstream ingress
changes (`twenty-kanban-webhook-ingress`, `customerio-consent-ingress`, later
`survey-engine-ingress`) enter after these rules exist, with no grandfathering
(`design/delivery/pulse-program-roadmap.md`).

## What Changes

- **Producer-policy classifier** (`pulse_core.producer_policy`): a pure function that extracts
  the declared event vocabulary from `packages/ocean` producer source — Literal/enum state
  vocabularies, event-model fields, entity-type declarations, and `event_type` string
  construction — and classifies each against the pinned catalog contract
  (`pulse_core.generated`: `SUBJECT_TYPES`, `TRANSITIONS`). A finding names the file, the schema
  element, and the catalog subject/state it collides with.
- **Subject-scoped matching, not bare strings**: ocean's existing vocabularies legitimately reuse
  words the catalog also uses (`AlertStatus` carries `open`/`resolved`; `TicketStatus` carries
  `open`/`in_progress`/`resolved`; both describe alert/ticket entities, which are not catalog
  subjects). The classifier flags a schema only when it addresses a catalog subject — by entity
  type, by subject-identifying state-set match, or by `event_type` addressing — so the current
  tree is green and a planted state-bearing emit is red (Demo 2 acceptance,
  `pulse-program-roadmap.md` §demo).
- **CI gate wired into `task check`**: a pytest under `tests/` runs the classifier over
  `packages/ocean` against the real catalog and fails on any finding — offline, fresh-clone-safe,
  no new Taskfile target needed (`tests/` is already in `TESTED_PATHS`).
- **False-positive suppressions, never exemptions**: a suppression file records adjudicated
  name-collision false positives with mandatory justification; the gate fails on a suppression
  entry that no longer matches anything (stale) or lacks justification. A genuinely
  state-asserting producer is never suppressed — it converts to an ingress adapter (§4.4); the
  file ships empty.
- **Policy documented where producers live**: the §4.4 rule (assert state → command; non-subject
  fact → direct emit; the classification test), the sanctioned command sources, and the
  what-to-do-when-red procedure recorded for ocean producer authors; `docs/contracts/consumes.md`
  gains the gate as a consumer of the pinned catalog contract.

## Capabilities

### New Capabilities

- `producer-policy`: the §4.4 classification test as an enforced offline CI gate — no producer
  schema in `packages/ocean` names a catalog state; subject-scoped matching; suppressions carry
  justification and expire when stale.

### Modified Capabilities

_None. `catalog-source` already pins the consumer contract this gate reads ("The consumer
contract is pinned" names `producer-ingress-policy`'s CI gate as its first consumer); consuming
it changes no catalog requirement. No ocean runtime behavior changes — the gate constrains
future schemas._

## Impact

- New `pulse_core.producer_policy` module (classifier + suppression loading), tested in
  `packages/pulse-core/tests/`.
- New repo-level gate `tests/test_producer_ingress_policy.py`, running under `task check` via the
  existing `TESTED_PATHS` — no `Taskfile.yml` or workflow edits.
- New suppression file under `packages/ocean/` (empty at ship) and a producer-policy section in
  `packages/ocean/docs/`; `docs/contracts/consumes.md` updated (the gate consumes
  `catalog/state_catalog.yaml` + `pulse_core.generated` and nothing else — no seed, no Snowflake
  rows, no generator internals).
- No PHI: the classifier reads committed source code and the catalog — no patient data anywhere;
  fixtures are synthetic schema files.
- No live network in tests: AST parsing over the working tree only; holds in a fresh clone
  (`.venv`, caches, and generated trees excluded by construction).
- Rollback: fully additive — reverting removes the module, the gate test, the suppression file,
  and the docs section; no producer code is touched by this change.
