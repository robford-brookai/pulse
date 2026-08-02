# PULSE program roadmap — waves, phases, stages

Status: provisional · 2026-08-02

The dispatchable truth for the active change is
`openspec/changes/ocean-eventbridge-migration/tasks.md`; this document is the program-level
projection over it and over the queued work that has no OpenSpec change yet. When they disagree,
`tasks.md` wins. Regenerate the status snapshot here whenever a wave closes.

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
| 0 — Absorption | S0.1 catalog spec, S0.2 catalog machinery | `ocean-eventbridge-migration` (DNA-733) | 0–4 + post-merge ops |
| 1 — Record | S1.1 ledger schema + command API | **queued — change not proposed** | — |
| 2 — Ingress | S2, plus S1.2 verdict-relay, S1.3 schedules, S1.4 identity | queued, gated on S1.1 | — |
| 3 — Projections | S3 (incl. migration M1) | queued | — |
| 4 — Retirement | S4 | queued | — |

## Active change: `ocean-eventbridge-migration`

Snapshot 2026-08-02 (after main `af49e70`): **19 / 50 tasks merged.**

| Wave | Tasks | State |
|---|---|---|
| 0 — absorption | 1.1–1.4 | ✅ complete |
| 1 — the two contracts | 2.1–2.2 | ✅ complete |
| 2a — sequence guards | 3.0–3.6 | 6/7 merged; 3.4 in review (PR #23) |
| 2b — publish sites | 4.1–4.13 | ✅ complete |
| 2b close | 4.14 | open — **serial**, must run with nothing else in flight |
| 2c — consumers | 5.1–5.7 | 5.1–5.3 in review (PRs #37–39); 5.4–5.7 open |
| 3 — infrastructure | 6.1–6.6 | 6.1 merged (landed early); 6.2–6.6 open |
| 4 — warehouse + equivalence + docs | 7.1–7.3, 8.1–8.2, 10.1–10.2 | open |
| post-merge — destructive ops | 9.1–9.3 (CCC lane) | held; 9.2 gated on 8.2 |

## Remaining waves — provisional master plan

Each wave: entry condition → contents → exit condition. Serial tasks release alone; everything
else in a wave fans out to parallel Orca worktrees.

### Wave 2a close
- Entry: PR #23 (3.4) review.
- Exit: all guards merged; 5.5/5.6 unlock.

### Wave 2b close — 4.14 (serial: workspace_roots)
- Entry: **all other worktrees merged or parked** — 4.14 edits `Taskfile.yml` (`TESTED_PATHS`)
  and hoists `_TOPIC_PREFIX`/`domain_for_topic` into `ocean_broker.catalog`, touching files every
  branch abuts.
- Contents: bring converted ocean services into `task test`. Until it lands, every wave-2b/2c test
  is invisible to CI — prioritize it over starting new 2c work.
- Exit: converted services' tests run in CI, or each exclusion is per-service with a stated reason.

### Wave 2c — consumers (5.1–5.7)
- Entry: per-consumer guard deps (5.4←3.6 ✅, 5.5←3.1–3.4, 5.6←3.5 ✅, 5.7←4.13 ✅).
- Contents: subscribe/poll/commit → receive/process/delete; ordering verdict in each HANDOFF.
- Exit: all seven merged; 6.6 and 7.1 unlock.

### Wave 3 — infrastructure (6.2–6.6)
- Entry: 6.2/6.4 are unlocked now (dep 6.1 ✅); 6.3←6.2; 6.5←6.2; 6.6←5.7 and is serial
  (workspace lockfile).
- Exit: rules/queues/DLQs/archive in terraform, LocalStack replaces Redpanda locally,
  `confluent_kafka` gone from manifests.

### Wave 4 — warehouse, equivalence, docs
- 7.1–7.3 (warehouse path), 8.1–8.2 (equivalence harness and Kafka-vs-LocalStack run),
  10.1–10.2 (ADR + contracts docs; 10.2 serial: openspec_main_specs).
- Exit: 8.2 recorded — this is the gate for MSK teardown.

### Post-merge — destructive ops (9.1–9.3, CCC lane)
- Never dispatched by `task dispatch`. Operator runbooks, G_APPROVAL per item.
- 9.1 terraform apply ← 6.4 + 8.2 · 9.2 MSK teardown ← 9.1 + 8.2 · 9.3 archive source repo ← 9.2.

### Then: change close
`task collect` → doc_update (specs land in `openspec/specs/` — the first baseline this repo will
have) → `task verify` → archive (G_DRIFT).

## Queued changes (no OpenSpec proposal yet)

Listed here so the roadmap is complete; propose each via `opsx:propose` when its gate clears.

| Queued change | Source spec | Gate |
|---|---|---|
| S1.1 ledger schema + command API client | `design/migration/rpc-object-model-assessment.md`, ADR §6 Phase 1 | `ocean-eventbridge-migration` through wave 4 (transport stable) |
| S1.2 verdict declare-back writer (`packages/verdict-relay`) | `design/delivery/pulse-s1-work-orders.md` | S1.1 |
| S1.3 clock-driven jobs (`packages/schedules`) | `design/delivery/pulse-s1-work-orders.md` | S1.1 |
| S1.4 identity resolution / TIDE matcher v1 (`packages/identity`) | `design/delivery/pulse-s1-work-orders.md` | S1.1 |
| BF-0a archaeology access | `design/migration/bf0-mongo-archaeology-agent-batch.md` | independent; operational-discovery lane |

Format note: `design/delivery/pulse-s1-work-orders.md` and
`design/migration/ocean-absorption-agent-batch.md` remain in the retired Open Engine format
(see `docs/process/workflow-drift-review.md`). Their *content* is current; their wrappers get
rewritten when each is turned into an OpenSpec change, not before. Do not dispatch from them
directly.

## Standing decisions recorded here

- Wave 2c and wave 3 tasks that are dependency-free are still **held behind 4.14's serial
  window** once the current in-flight PRs merge — CI blindness compounds with every unverified
  conversion.
- Waves within the active change are enforced by `task dispatch` (dependency graph + serial
  lanes); this roadmap adds only the cross-change ordering, which no tool enforces yet.
