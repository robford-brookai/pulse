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

## Program change ladder — to completion

Every remaining unit of work, grouped by phase. Each row: change id, source, gate (entry
condition). Waves inside each change are that change's `tasks.md` concern; this ladder adds only
cross-change ordering. Propose each via `opsx:propose` when its gate clears. Per-phase **Done
means** lines quote ADR §6 exits verbatim.

### Now — gate-free

| Change | Source | Gate |
|---|---|---|
| `bf0a-archaeology-access` | `design/migration/bf0-mongo-archaeology-agent-batch.md` | none (repo_change; G_HARDENING receipted) |
| `synthea-seed` | `design/delivery/pulse-runtime-readiness.md` §2.2 | none (repo_change) |

### Phase 2 — Ingress

Gate for the S1.x siblings: `pulse-ledger-core` through wave 4 (task 5.2 / DNA-799 pins client
path, read endpoints, quarantine table, cursor facility, handler signature).

| Change | Delivers | Gate |
|---|---|---|
| `s12-verdict-relay` | `packages/verdict-relay` per the S1 work order; supersedes the clinic-rules-engine Snowpark emitter (P5) | S1.1 wave 4 |
| `s13-schedules` | `packages/schedules` — month-open + D9 consent sweep | S1.1 wave 4 |
| `s14-identity` | `packages/identity` — deterministic matcher v1; also genesis's matcher | S1.1 wave 4 |
| `catalog-authority` | authoritative `state_catalog.yaml` replacing the Appendix C seed; regeneration into the 2.1 generator; D18 Snowflake release job + breaking-change rule. Serial lane `catalog_generated_surfaces` | D18 confirmed |
| `twenty-kanban-webhook-ingress` | D8: enable the HMAC route 3.4 ships disabled; drag → command; invalid → rejection + card comment (heal-back write completes in Phase 3) | D15 confirmed |
| `customerio-consent-ingress` | D9 forward consent ingress, actor `customer.io`, message-level provenance | export/webhook mechanism confirmed |
| `producer-ingress-policy` | the ADR §4.4 CI gate: no producer schema in `packages/ocean` names a catalog state; wired into `task check` | `catalog-authority` |

**Done means (ADR §6):** "Zero direct emits of catalog-state events, checked in CI against
producer schemas" — plus all four sanctioned command sources live (kanban webhook, Customer.io
ingress, identity service, verdict relay) and the Demo 2 receipt attached.

### Phase 3 — Projections

Gate: Phase 2 exit; Twenty dev instance from `environment-matrix`.

| Change | Delivers | Gate |
|---|---|---|
| `pulse-app-scaffold` | Twenty app package (`create-twenty-app`), objects, roles, `project-domain-event` logic function, catalog → SELECT-options codegen | **D4** (artifact vs live-apply) |
| `twenty-projection` | ledger-fed consumer: upserts on `(subject_id, ledger_seq)`, monotonic apply, heal-back write (closes D8 end-to-end), read-only status fields | `pulse-app-scaffold` |
| `customerio-projection` | segment/attribute sync from ledger events | Phase 2 exit |
| `snowflake-projection` | STG_EVENTS ledger contract (flat projection proven in S1.1 task 5.1) atop the existing `OCEAN_RAW.EVENTS` landing | Phase 2 exit |
| `reconciliation-sweeps` | per-family referee sweeps generalizing S1.3's consent sweep; corrections actor `reconciliation`; optional legacy-inference drift sentinel (legacy-harvest #4) | `snowflake-projection` |
| `projection-rebuild-drill` | ADR §4.6 authoritative rebuild as a drill; **carries Demo 3** | `twenty-projection` |
| `m1-retire-patient-state` | ADR §6.2: `patients` rows only from ledger projection; three read surfaces cut over; `enrollment_status` read-only; `alerts.py` bootstrap insert deleted | `twenty-projection` |

**Done means (ADR §6):** "Reconciliation clean over one full cycle. Projections rebuild from
ledger in a drill. M1 retired — no consumer writes `patients.enrollment_status`."

### Phase 4 — Retirement

Gate: Phase 3 exit.

| Change | Delivers | Gate |
|---|---|---|
| `dbt-derived-state-retirement` | derived-state models become verdict runners (declared per I3 via verdict-relay) or are deleted; CI dbt-manifest scan enforces | Phase 3 exit + `s12-verdict-relay` |
| `odg-read-redirect` | remaining PRM current-state reads → projections; funnel marts (`fct_status_transitions`, `fct_patient_status_daily`) on ledger + verdict chain; **carries Demo 4** | `dbt-derived-state-retirement` |

**Done means (ADR §6):** "No warehouse model answers 'what is this patient's status' by
inference. Funnel counts read the ledger + verdict chain."

### Genesis and cutover

Gate: `s14-identity` merged, quarantine-reviewer role filled, `synthea-seed` merged.

| Unit | Delivers | Gate |
|---|---|---|
| `genesis-adjudication-rules` | versioned dbt referee rules per genesis §2, `genesis_rule_version` on every event, re-run diff reports, quarantine routing | gates above |
| `genesis-seed-run` | **BF-4 seed = genesis run, one act (P4)**: one batch harness (the BF-3 remainder), actor `migration:<run_id>`; Synthea rehearsal repo_change; production run operational + G_APPROVAL (C1 cleared — no longer a blocker); **carries the genesis rehearsal demo** | `genesis-adjudication-rules` |
| `pocar-relay` | POCAR change events replayed as attributed commands; P1's existing-patient path; P2's rollback lever | S1.1 (client), D15 creds |
| Cutover P0→P3 | ops runbook ladder, not an OpenSpec change. Exits per genesis §3: P0 drift < tolerance 10 consecutive business days per family (needs G-2) → P1 100% net-new referrals ledger-native one full billing month → P2 per-family flips Referral → Consent → Enrollment → BillingEpisode, ≥1 week apart, rollback = re-enable relay (needs G-3, enablement, paging) → P3 zero POCAR writes 30 days | `genesis-seed-run`, `pocar-relay` |

**Genesis done means (genesis §4):** one genesis event with provenance per live in-scope object;
ledger funnel counts match referee within tolerance (exact for Enrollment/BillingEpisode, ±1%
pre-enrollment pending G-2); quarantine drained or owned with disposition dates; re-run
byte-identical.

### Backfill (orders BF-0…BF-6 — Stage 2 never blocks cutover)

| Order | Vehicle | Gate |
|---|---|---|
| BF-0a | `bf0a-archaeology-access` (now) | none |
| BF-0b archaeology report | operational_discovery session, outside Orca | BF-0a merged + Mongo read-only creds |
| BF-0c satellite stores | blocked placeholder | interview items 3–8, 10 |
| BF-1 TIDE absorption → `packages/identity` | destructive_ops (git surgery) + repo_change (conform) | OCN playbook rerun; sequence with `s14-identity` |
| BF-2 identity backfill run | operational + G_APPROVAL | BF-1 + `s14-identity`; match-rate report |
| BF-3 loader + bulk mode | **delivered by `pulse-ledger-core`** (tasks 1.2, 3.5) | closed at S1.1 archive |
| BF-4 seed | = `genesis-seed-run` (one act, above) | see genesis |
| BF-5 history, 8 grains in §5 priority order | repo_change (dbt rules) + operational + G_APPROVAL (loads), one sub-order per grain | BF-0b evidence ceilings; BF-D1 horizon; seam-continuity per grain |
| BF-6 epoch wiring + marts | repo_change | BF-D2 floors; aggregate-sanity report is the receipt |

### Runtime and ops

| Unit | Delivers | Gate |
|---|---|---|
| `d14-spcs-latency-spike` | one-day webhook-latency spike (operational_discovery; report, not diff). **Highest-leverage unblock** | none |
| `pulse-spcs-deployment` | service spec, Snowflake Secrets, ingress, image pinning (thin wrapper, never a fork — AGPL §13) | D14 |
| `environment-matrix` | dev/staging/prod per runtime-readiness §2.1; staging regen consumes `synthea-seed`; gates Demo 3's staging leg and cutover P0 | `synthea-seed` |
| `observability` | Datadog monitor set + three SLOs per §1.5; S1.2/S1.3 ship their own runbooks — this wires monitors and paging | before P1; paging before P2 |
| Roles / on-call / enablement | exec-session register rows, not changes | — |

## Positions taken (doc conflicts; edits deferred)

- **P1 — Ledger-as-record wins** over the 2026-07-28 Twenty-as-ingest docs
  (`event-envelope-spec.md` accept-and-flag, `event-state-platform-solution.md` MCP write path,
  `clinic-rules-engine.md` Snowpark emitter, `twenty-data-model.md` LWW projection). S1.1 task
  5.2 adds supersession notes to envelope + state-catalog; queued change `v1-docs-cleanup`
  sweeps the rest.
- **P2 — C1 cleared 2026-07-31** (Snowflake BAA covers Snowflake Postgres). Synthea stays the
  non-prod standard; stale "C1 gated" language falls under `v1-docs-cleanup`.
- **P3 — BF naming**: orders keep BF-0…BF-6; the backfill plan §8 decisions rename to
  BF-D1…BF-D5. BF-D5 (bitemporal I10) is resolved — it landed in `pulse-ledger-core` task 1.2.
- **P4 — BF-4 seed = genesis run**: one act, one harness, actor `migration:<run_id>`.
- **P5 — Verdict path**: `s12-verdict-relay` supersedes the clinic-rules-engine emitter; the
  qualification mart becomes a consumed contract in `docs/contracts/consumes.md`.
- **P6 — Signal adapter superseded**: forward role by ingress adapters (ADR §4.4), backfill role
  by the BF ladder; the drift-detector idea survives as the reconciliation sentinel option.
- **P7 — TIDE retires as a name** at BF-1 — "person key", `packages/identity`.

## Open decision register

| ID | Decision | Gates | Owner |
|---|---|---|---|
| D4 | Catalog→Twenty generator: artifact vs live-apply | `pulse-app-scaffold` codegen | Ford |
| D14 | SPCS vs EKS (spike first) | `pulse-spcs-deployment` | Tal + Ford |
| D15–D18 | Auth / idempotency / outbox / catalog SoR — recommended; close at exec session | D15: kanban ingress; D18: `catalog-authority` | per runtime-readiness §5 |
| G-1 | Historical closed objects excluded from genesis | genesis scope | Tal |
| G-2 | Drift tolerance per family | cutover P0 exit | Ethan + Luke |
| G-3 | Per-family flip dates | cutover P2 | Ford + Tal (after P0) |
| BF-D1 | Backfill horizon (24 mo recommended) | BF-5 scope | Oren + Tal |
| BF-D2 | Evidence floors per metric | BF-6 | Ford + Luke |
| BF-D3 | Genesis re-anchoring convention | BF-5 loader semantics | Tal |
| BF-D4 | Billy import semantics | BF-5 grain 6 | Ethan |
| Roles | quarantine reviewer (before genesis P0), compliance owner (before exec session), verdict steward (Luke, confirm), on-call (before P1), enablement lead (Carin, confirm) | as noted | exec session |
| §8.1 | Object-model confirmation receipts (D2, D8, D9) | hygiene | Tal (+compliance for D9) |

## Program done

Phase 4 exit + genesis acceptance (genesis §4 a–d) + cutover P3 exit (zero POCAR writes for 30
days). Stage 2 history is explicitly **not** in program-done: it lands per grain behind the
seam, each grain signed off by its seam-continuity check, indefinitely after cutover.

## Demo breakpoints

Convention: each demo is the **final task of the phase-closing change** — a runnable script
under `scripts/demo/`, a runbook under `docs/runbooks/`, and a receipt (script output) attached
to the change's Linear parent before archive. Scripts exit nonzero on any failed assertion.
Demos run against LocalStack / fixtures / Synthea only — never PHI, never live prod. Demo
scripts are not tests: they need LocalStack up, so they stay out of `task check` (a smoke-parse
test may cover them).

| Demo | Closes | Shows |
|---|---|---|
| 1 | Phase 1 (`pulse-ledger-core`, task 5.3) | LocalStack: legal command commits and lands on the queue; illegal rejects with catalog reason + version; replay returns the original event id; independent fold equals `current_state` (wraps the 5.1 harness) |
| 2 | Phase 2 (`producer-ingress-policy`) | HMAC-signed synthetic drag → commit; invalid drag → rejection receipt; consent fixture recorded actor `customer.io`; verdict declared from fixture mart with skip-stale proof; producer-policy gate red on a planted state-bearing emit, green after removal |
| 3 | Phase 3 (`projection-rebuild-drill`) | rebuild drill: seed Synthea events → project → destroy → rebuild from ledger → row-identical; live heal-back inside the 60 s freshness budget; M1 receipt |
| 4 | Phase 4 (`odg-read-redirect`) | funnel stock + flow counts from ledger + verdict chain; diff against the retired dbt models' frozen outputs; CI proof zero inference models remain |
| Genesis rehearsal | `genesis-seed-run` | full genesis on a frozen Synthea snapshot; re-run byte-identical (checksum diff empty); amended-rule re-run yields a diff report; quarantine populated by `synthea-seed`'s engineered contradictions |
| Cutover go/no-go | each P-phase runbook | receipt pack per exit: P0 10-day drift streak per family; P1 referral-native count over one billing month; P2 flip receipts + rollback drill; P3 POCAR-write monitor at zero for 30 days |

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
