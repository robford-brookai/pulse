# PULSE presentation brief — 2026-08-19

## 1.0 TL;DR

Last week they heard the framing. This week they get receipts. The room's test is concrete: can PULSE operate billing logic at no more than 10-15 minutes of latency for work-effort optimization. The answer you can defend: every leg of that loop except the analytics compute is already receipted at seconds against live infrastructure (last night: nine scripted assertions green plus a literal hand drag committing one correctly-timed event), and the analytics leg is a scheduling knob, not a physics problem — the billing demo timing the whole loop end to end is in preparation now on a parallel thread. Keep the frame: "the patient unified ledger of state and events — a recorder of events minted natively in each system, entered into the common ledger." Twenty stays headless and unnamed. One ask to close: pick the first producer system to integrate through the command API.

## 2.0 The framing, and why it holds

### 2.1 The sentence to repeat
"PULSE is the patient unified ledger of state and events. Each system keeps minting its own events natively. PULSE records them on one governed ledger, and every downstream view — boards, warehouses, campaigns — is a projection of that ledger, never a second source of truth."

### 2.2 What "headless" means here, concretely
- Twenty holds no authority. Its objects, fields, and roles are generated from a versioned state catalog and applied by a deterministic artifact — the workspace model is code-reviewed in the repo, not configured by hand in a UI.
- Writes flow one way. A board drag becomes a signed webhook, which becomes an attributed command on the ledger's single write path. The board is an input device and a display, not a database.
- Nothing anyone does in the UI can corrupt state. The catalog decides legality at write time. Last night two illegal drags were refused with the exact rule that refused them, and the state of record did not move.

### 2.3 The slow reveal, managed
The PRM value is real — a 10-years-more-modern interface and faster time-to-value for patient coaching — but saying "new UI" tomorrow invites a replacement debate you do not need. The sequence that avoids it:
- Now: "a governed event backbone with projections."
- When someone notices the board is pleasant: "projections are cheap once the ledger exists — this one took one change."
- Only when pulled: the coaching-efficiency story, framed as a consequence of projections, never the reason for the platform.

## 3.0 Proof points (all dated, all receipted)

```
Milestone                       Date        Receipt
Catalog v1.0.0 authoritative    2026-08-07  archived change, Snowflake release machinery
Phase 2 complete, v2.0          2026-08-08  all four command sources live, CI gate on producers
Twenty dev instance (v2.30.0)   2026-08-16  DNA-909, F1 gate positive
Metadata artifact live-verified 2026-08-17  49/49 operations read back, re-apply all no-ops
pulse-app-scaffold archived     2026-08-17  11/11 tasks, PRs #196-#213, baseline updated
Demo 3: nine assertions green   2026-08-18  exit 0, receipts on issue #223
Hand drag committed             2026-08-18  one event, disposition=committed, board and ledger agree
Illegal drags rejected (2)      2026-08-18  genesis rule, written reason on each card
```

### 3.1 The demo ladder — three demos, one escalating claim

Each phase closed with a runnable, receipted demo. Together they tell one story: the same guarantees, proven against progressively more real infrastructure. All three are re-runnable tomorrow from this repo.

| Demo | Proves | Runs against | Command |
|---|---|---|---|
| 1 — Ledger core (Phase 1) | legal commit lands on the queue, illegal rejects with the rule, replay returns the same event once, independent fold of raw events equals current state | LocalStack + Postgres, fixtures | `uv run python scripts/demo/demo1_ledger_core.py` |
| 2 — Identity + schedules (Phase 2, partial) | exact-match, mint, quarantine, and conflict-split identity decisions with rule ids as evidence, plus month-open and consent-sweep dry-runs where Customer.io wins every conflict | fixtures only — no Docker, no network | `uv run python scripts/demo/demo2_identity_matcher.py` and the schedules CLI (runbook: demo2-partial-s13-s14) |
| 3 — Live kanban round trip (Phase 3, last night) | all of the above semantics against a live Twenty server: nine assertions green, one hand drag committed, two illegal drags rejected with written reasons | live dev instance, synthetic data | receipts on issue #223; runbook and script in-repo |
| 4 — Billing latency (in preparation, parallel thread) | billing logic operating end to end inside a 10-15 minute window: a work-effort event in, the qualification verdict computed, the billing state moved — wall-clocked | live dev instance + warehouse cadence | target demo for the work-effort optimization claim, being prepared now |

The escalation is the pitch: Demo 1 proved the ledger's rules in a sandbox, Demo 2 proved the domain logic offline, Demo 3 proved the whole loop against real software with a human at the keyboard, and Demo 4 puts a stopwatch on the business claim. Nothing was simulated away.

### 3.1.1 The billing-latency budget — where the 10-15 minutes actually goes

The pipeline for billing logic already exists as shipped, receipted pieces. The only leg that consumes minutes is the one that is supposed to: the analytics compute cadence. Present the budget, not just the target.

| Leg | Mechanism (shipped change) | Latency | Evidence status |
|---|---|---|---|
| Work-effort event minted natively, entered on the ledger | command API, signed webhook or SDK (`pulse-ledger-core`, Phase 2 ingresses) | sub-second | receipted live, Demo 3 |
| Ledger to distribution and warehouse landing | outbox to EventBridge/SQS, landing in `OCEAN_RAW.EVENTS` | seconds | Demo 1 shows commit-to-queue, landing table shipped Phase 0 |
| Billing and qualification logic | dbt-computed verdict mart, swept by the verdict relay (`s12-verdict-relay`) which declares verdicts back onto the ledger with a durable cursor | the cadence knob — schedule mart plus relay at 10 minutes and the ceiling is the schedule plus compute | shipped and demoed Phase 2; the 10-minute cadence is what Demo 4 wall-clocks |
| Verdict to the board (billing state visible to coaches) | projection of `qualificationStatus` (the `billing_episode` dimension) | seconds once the projection trigger lands (`twenty-projection`, next change) | board write path proven; live trigger is the named next change |

The sentence that carries it: "Every leg except the analytics compute already runs in seconds against live infrastructure with receipts. The compute is a schedule we set. The demo in preparation runs the loop with a stopwatch — event in, verdict computed, billing state moved — inside the window."

Two honesty notes so the claim survives scrutiny: the 10-15 minute figure is a cadence commitment, not a burst-throughput claim, and the final board-visibility leg rides the `twenty-projection` change whose gate opened this week — the demo lands after it does.

Recommended live moment for tomorrow, ranked by impact per minute of risk:
1. Show Demo 3's receipt table on issue #223 (zero risk, already happened, timestamped).
2. Re-run Demo 1 live (self-contained, brings its own stack up, ends with the fold-equals-state proof).
3. A live drag on the dev board only if the room earns it — it works, but it needs the dev instance reachable and a refresh to show the result.

### 3.2 The demo-3 story, in the order it lands
1. A coach drags a card. One correctly-timed event lands on the ledger — `effective_at` equals the record's own stamp, not the wall clock.
2. The same webhook delivered twice produces the same event once. Replays are free.
3. An illegal drag comes back rejected with the catalog rule that refused it, a note on the card, and zero state change. This happened twice last night by accident, to a real person, and the system explained itself both times.

### 3.3 Numbers if asked
```
Live workspace        2 programs, 20 synthetic patients, 24 patient-program pairs
Artifact              49 metadata operations, byte-identical re-render, CI-validated
Assertions            9/9 green, exit 0, plus 1 hand-drag commit and 2 live rejections
Falsified-then-fixed  6 API shape guesses corrected against the live server in 2 days
Data                  synthetic only — no PHI has touched any of this
```

## 4.0 Vocabulary discipline

| Say | Not |
|---|---|
| ledger, event backbone, system of record for events | platform migration, new system |
| projection, view of the ledger | UI, replacement, new PRM |
| recorder of natively-minted events | integration hub, middleware |
| governed write path, catalog legality | validation layer |
| headless projection target | Twenty, CRM |
| proven against a live instance | pilot, beta |

Two hard avoids from the standing DNA-900 framing: never "UI replacement," never "pilot-ready." The demo is engineering proof, not a rollout.

## 5.0 Likely questions, with answers

- "Is this a new UI we have to adopt?" — No. Nothing changes for any existing system. PULSE records events those systems already mint. The board you saw is one projection, and projections are optional and disposable.
- "Why Twenty?" — It is a modern, open-source, self-hosted substrate we control completely: its entire workspace model is generated from our catalog and applied as a reviewed artifact. If it disappeared tomorrow, the ledger and every other projection survive untouched. Pinned at v2.30.0, deliberate upgrades only.
- "Is it in production?" — Dev only, synthetic data only, and the promotion path is already written: the same artifact applies to staging and prod, rollback is re-applying the prior artifact. ADR-0004's deployment decision stays open on purpose.
- "What about PHI?" — None involved. The population is synthetic. The architecture is PHI-conscious by construction: receipts, logs, and rejection notes carry identifiers, states, and reason codes — never payload values.
- "How do systems integrate?" — One HTTP command API. Each producer holds its own credential, the actor is derived server-side, idempotency is built in, and an illegal event is refused with the reason and catalog version. Reads come from projections or the event feed, so no consumer ever queries another's database.
- "Can it really do billing in 10-15 minutes?" — Walk the budget table (3.1.1). Every leg except analytics compute is receipted at seconds. The compute is a schedule we choose, and the stopwatch demo proving the full loop is in preparation — commit to a date rather than improvising one in the room.
- "What breaks if the ledger is wrong?" — The ledger is append-only and bitemporal, so "wrong" is corrected by another event, never an edit. Projections rebuild from scratch as a drill (that rebuild is a scheduled change with its own demo).
- "What did last night actually prove?" — That the hard bit works end to end against real software: identity round-trips, deterministic metadata, idempotent writes, catalog enforcement, and honest rejection — witnessed, not simulated.

## 6.0 Honest edges, if pressed

- The projection function's live trigger is not installed yet — ledger-to-board heal-back is the next change (`twenty-projection`), and its gate opened when the scaffold archived.
- A rejected drag currently leaves the card in the wrong column until refresh. Known, documented, and a design input for the projection change — the ledger is correct throughout.
- No general HTTP read API exists by design today. Consumers use projections or the feed. A concrete producer needing remote reads would trigger a roadmap conversation, not a workaround.

## 7.0 Next step to ask for

Agreement that the next producer integration goes through the command API — pick one candidate system in the room. That converts the demo into a commitment without ever mentioning a UI.
