# PULSE program roadmap — waves, phases, stages

Status: provisional · 2026-08-03

The dispatchable truth for the active change is
`openspec/changes/pulse-ledger-core/tasks.md`; this document is the program-level projection over
it and over the queued work that has no OpenSpec change yet. When they disagree, `tasks.md` wins.
Regenerate the status snapshot here whenever a wave closes.

## The three sequencing vocabularies

The program is described at three grains, each owned by a different artifact. They are not
competing plans — they nest.

| Vocabulary | Grain | Owner | Meaning |
|---|---|---|---|
| **Wave** (0, 1, 2a…) | dispatch batches inside one OpenSpec change | `tasks.md` annotations, `docs/process/dispatch-template.md` §2 | A human-sized release of parallel tasks. The dependency graph is the truth; the wave label is documentation cross-checked against it. |
| **Phase** (0–4) | program milestones of the OCEAN→PULSE migration | ADR `design/migration/ocean-to-pulse-adaptation-plan.md` §6 | Absorption → Record → Ingress → Projections → Retirement. |
| **S-stage** (S0.x, S1.x…) | build order of PULSE platform capabilities | `design/delivery/pulse-s1-work-orders.md`, `design/migration/pulse-ledger-backfill-plan.md` | What gets built, independent of which repo change delivers it. |

Crosswalk:

| Phase (ADR §6) | S-stages | Delivery vehicle | Waves |
|---|---|---|---|
| 0 — Absorption | S0.1 catalog spec, S0.2 catalog machinery | ✅ complete — `ocean-eventbridge-migration` (DNA-733), archived `2026-08-02-ocean-eventbridge-migration`, specs baseline seeded | 0–4 + post-merge ops, all done |
| 1 — Record | S1.1 ledger schema + command API | **active — `pulse-ledger-core` (DNA-784)** | 0–4 |
| 2 — Ingress | S2, plus S1.2 verdict-relay, S1.3 schedules, S1.4 identity | queued, gated on S1.1 | — |
| 3 — Projections | S3 (incl. migration M1) | queued | — |
| 4 — Retirement | S4 | queued | — |

## Completed changes

- `ocean-eventbridge-migration` (DNA-733) — 56/56 tasks. Archived at
  `openspec/changes/archive/2026-08-02-ocean-eventbridge-migration/`; its five delta specs seeded
  `openspec/specs/` as the repo's first baseline. Out-of-lane ops executed: terraform applied,
  MSK Serverless torn down, `robford-brookai/ocean` archived read-only with the ADR §7
  supersession notice as its final commit.

## Active change: `pulse-ledger-core` (S1.1)

Snapshot 2026-08-03 (after main `908b10d`): **1 / 15 tasks merged.**

| Wave | Tasks | State |
|---|---|---|
| 0 — schema and scaffold | 1.1–1.2 | 1.1 ✅ (#70); 1.2 in flight (worktree task-002) |
| 1 — generated command surface | 2.1 | held — serial, releases when 1.2 merges |
| 2 — the write path | 3.1–3.5 | held |
| 3 — reads, client, distribution | 4.1–4.5 | held |
| 4 — proof and documentation | 5.1–5.2 | held |

## Remaining waves — provisional master plan

Each wave: entry condition → contents → exit condition. Serial tasks release alone; everything
else in a wave fans out to parallel Orca worktrees. Three serial lanes run through this change:
`workspace_roots` (1.1), `alembic_sequence` (1.2 — new sequence under
`packages/pulse-ledger/infra/postgres/`), `catalog_generated_surfaces` (2.1), and the
`openspec_main_specs` doc-updater lane (5.2).

### The serial opening: 1.2 → 2.1 → 3.1 → 3.2

- 1.2 lands the ledger schema alone (bitemporal events, co-committed state, idempotency keys,
  outbox, writer state, review queue; REVOKE UPDATE/DELETE on events).
- 2.1 lands the catalog → command-type generator alone (generated adjacency + Pydantic types).
- 3.1 (validation core) needs both; 3.2 (transactional commit path) needs 3.1. The chain is
  one-at-a-time by dependency until here.

### First parallel batch — after 3.2 merges

- 3.3 idempotency, 3.4 auth/attribution, 4.1 read APIs, 4.4 outbox relay — four worktrees at
  once. 3.5 follows 3.3+3.4; 4.2 follows 3.4; 4.3 follows 3.3+3.5; 4.5 follows 4.4.
- Exit: write path complete (idempotent, attributed, backfill-capable), reads and relay in place,
  LocalStack shows a committed event on a queue.

### Wave 4 close — 5.1 then 5.2

- 5.1 end-to-end proof: independent fold equals `current_state`; STG flat-projection contract
  holds.
- 5.2 (serial, doc-updater lane): pin the downstream "confirm path" names in
  `pulse-s1-work-orders.md`, supersession notes on the v1 envelope/state-catalog docs, ADR,
  contracts. This is also where this roadmap's queued table gets its next refresh.

### Then: change close

`task collect` → doc_update (delta specs fold into `openspec/specs/`) → `task verify` → archive
(G_DRIFT) → propose the S1.2/S1.3/S1.4 changes, which can run as parallel sibling changes.

## Queued changes (no OpenSpec proposal yet)

Listed here so the roadmap is complete; propose each via `opsx:propose` when its gate clears.

| Queued change | Source spec | Gate |
|---|---|---|
| S1.2 verdict declare-back writer (`packages/verdict-relay`) | `design/delivery/pulse-s1-work-orders.md` | `pulse-ledger-core` through wave 4 (5.2/DNA-799 pins its paths) |
| S1.3 clock-driven jobs (`packages/schedules`) | `design/delivery/pulse-s1-work-orders.md` | same |
| S1.4 identity resolution / matcher v1 (`packages/identity`) | `design/delivery/pulse-s1-work-orders.md` | same |
| BF-0a archaeology access | `design/migration/bf0-mongo-archaeology-agent-batch.md` | independent; operational-discovery lane |

Format note: `design/delivery/pulse-s1-work-orders.md` and
`design/migration/ocean-absorption-agent-batch.md` remain in the retired Open Engine format
(see `docs/process/workflow-drift-review.md`). Their *content* is current; their wrappers get
rewritten when each is turned into an OpenSpec change, not before. Do not dispatch from them
directly.

## Standing decisions recorded here

- Waves within the active change are enforced by `task dispatch` (dependency graph + serial
  lanes); this roadmap adds only the cross-change ordering, which no tool enforces yet.
- Orca `agentDefaultArgs` for `claude`/`claude-agent-teams` stays `--permission-mode acceptEdits`
  (the receipted H4 standard). Dispatch checks this live; loosening it is a receipted
  `exceptions.H4` entry in `.orca/hardening-receipt.json`, never a silent toggle. If worktree
  agents stall on permission prompts, the fix is project-scoped `permissions.allow` rules, not
  bypass.
