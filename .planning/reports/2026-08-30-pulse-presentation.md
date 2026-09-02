# PULSE — The Patient Unified Ledger, Explained

**TL;DR:** Pulse is Brook's single source of truth for patient state. It keeps one
tamper-proof journal of everything that happens to a patient's care journey — enrolled,
consented, qualified for billing, insurance verified — and one always-current answer to "what
is true right now." Every other Brook system either reports facts into it or reads answers out
of it, instead of each keeping its own version of the truth. All four of its demonstration
scripts passed live this week (as of 2026-08-30), which means the core promises below are
proven behavior, not plans.

---

## 1.0 The purpose — one truth instead of many copies

Ask three Brook systems "is this patient actively enrolled?" today and you can get three
answers, because each one re-computes the answer from its own copy of history. That is how
billing disputes, stale dashboards, and "the spreadsheet says otherwise" happen.

Pulse fixes this the way a bank fixes it. Your bank does not argue about your balance: it
keeps a statement (every transaction, permanent, in order) and a balance (the current number,
updated with each transaction). Pulse is that pattern for patient care state:

- **The journal** — every state change ever declared, who declared it, when it was true in
the world, and when Pulse learned it. Nothing is ever edited or deleted. A mistake is
corrected by a new entry that reverses the old one, so the full history stays readable.
- **The current answer** — for every tracked subject (a referral, an enrollment, a billing
episode, an insurance coverage), exactly one row saying what state it is in right now,
updated in the same instant as the journal entry that changed it.

The purpose, in one sentence: **no Brook system should ever have to infer patient state from
history again — they ask Pulse, and Pulse's answer is the answer.**

## 2.0 How it works — five parts, plain language


| Part                | What it is                                                                                                                                                                                                   | Everyday analogy                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **The catalog**     | The rulebook: every state a subject can be in, and every legal move between states. Versioned, released like software (currently version 1.1.0).                                                             | The rules of chess — you cannot move a rook diagonally, and you cannot move a patient from "active" straight to "pending start" |
| **The ledger**      | The journal plus the current answer, described above.                                                                                                                                                        | Bank statement plus bank balance                                                                                                |
| **The command API** | The single front door. Every system that wants to declare a fact submits it here, with credentials. The door checks the rulebook before anything is written.                                                 | A bank teller who checks your ID and the rules before posting a transaction                                                     |
| **The event bus**   | The announcement system. Every accepted fact is broadcast so downstream systems can react — no one has to poll or ask twice.                                                                                 | A public-address system: one announcement, every department hears it                                                            |
| **Projections**     | Read-only views painted from the ledger for specific audiences — for example the care team's kanban board. A view can be deleted and rebuilt from the journal at any time, because the journal is the truth. | A scoreboard: useful to look at, but the referee's book decides the game                                                        |


Two properties run through all five parts and are worth calling out to any audience:

1. **Idempotency** — submitting the same fact twice can never create two entries. The second
 submission gets back the original entry's receipt. This is what makes retries, network
 hiccups, and re-runs safe.
2. **Attribution** — every entry names the system or person who declared it, taken from
 verified credentials, never from what the sender typed. You always know who said so.

## 3.0 The features, proven by the demo

One script, `demo5_end_to_end.py`, walks a single synthetic patient through every seam Pulse
owns, in order, and stops the moment any door's promise stops holding. It runs in about five
minutes on a laptop (`task demo:e2e`) or, unchanged, against the real development environment
in an attended session (`task demo:e2e:live`). Demos 1 through 4 (below, §3.1) proved each door
works in isolation; this is the same patient walking through all of them, in the order any real
patient actually would.

1. **A referral arrives, and identity resolves it.** Three referral variants land in a fixed
order: the first mints a brand-new patient, the second matches an existing one by an exact
identifier, and the third — ambiguous — is quarantined for a human instead of guessed at. This
is Demo 2's identity leg, now the walk's front door.
2. **Consent lands, attributed.** A Customer.io consent export row lands in the warehouse.
Pulse sweeps it and records the patient's consent state with Customer.io itself as the source —
sweeping the same row twice changes nothing the second time.
3. **The care team drags a card, and the board is a door with a lock.** A correctly signed drag
commits one ledger entry. An illegal drag is refused with the rulebook's own reason and one
explanatory note on the card. A drag carrying a tampered signature is turned away before any
rule even runs. This is Demo 3's kanban leg, live.
4. **A verdict becomes billing and coverage state.** A billing verdict for the patient's episode
arrives from the analytics pipeline's mart. Pulse's relay files it and the state change it
justifies — the coverage subject is created on first sight, and an immediate re-run changes
nothing. This is Demo 4, live.
5. **Every view agrees with the ledger.** The care-team board, the warehouse's copy of the
journal, and an independent re-reading of the raw journal are each checked against the ledger's
own current answer for everything this patient touched. No disagreement survives to this point
in the walk.
6. **The rebuild drill.** The board's rows for this patient are deleted outright, then
repainted from nothing but the journal. The repainted rows match the deleted ones exactly — the
proof that a projection really is just a view, disposable and rebuildable, never a second copy
of the truth.

A clean run ends with a receipt naming every stage, how many things it checked, and which
subjects it touched — never a real name, a payload value, or anything that could be mistaken
for protected health information. A broken door stops the walk right there and says which check
failed, so nothing later runs on top of a false premise.

### 3.1 The four doors, one at a time

The walk above is the story a real patient lives. Each door was proven on its own first, and
those standalone demos still run and still matter — they are the fastest way to show one
capability without setting up the whole walk.

| Demo | What it proves alone | Runs against |
| --- | --- | --- |
| 1 — The record keeps honest books | a legal state change is accepted and announced; an illegal one is refused with the rule; a duplicate submission returns the original receipt with no second entry; an independent re-reading of the whole journal lands on the same current answer | a laptop, no live systems |
| 2 — The doors check identity and credentials | exact-match, mint, and quarantine identity decisions; a signed board move commits, an illegal one is refused with a comment on the card, a tampered signature is turned away entirely | offline fixtures |
| 3 — The board is a window, not a copy | dragging a card through a legal move becomes a ledger entry live, against the real board; an illegal move is rejected, snaps back, and gets an explanatory note; replays produce no second entry | live development environment |
| 4 — Billing and coverage become continuously known | a verdict from the analytics pipeline files as evidence plus its consequence; a patient-and-payer pair Pulse has never seen mints a coverage subject on the spot; re-runs change nothing | live development environment |

## 4.0 What Pulse depends on, and what depends on Pulse

Pulse never reaches into another system's database. Every connection is a published surface —
a warehouse table, an API, or a released package — so each team can change its internals
without breaking anyone. The map (current as of 2026-08-30):


| Brook system                                    | Direction            | The relationship in one line                                                                                                                                                 |
| ----------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The Snowflake warehouse** | both | Pulse lands an analytics *copy* of its journal in the warehouse (the live journal itself lives in Pulse's own Postgres database), and reads back two Snowflake-only surfaces: the verdict mart and the Customer.io consent export. Neither ever touches Pulse's operational database directly |
| **data-platform** (the dbt analytics project) | into Pulse | Its "management" dbt project computes the verdict mart — the eligibility and coverage verdicts Pulse's relay turns into billing and coverage state. This is also where the cpt-om CPT revenue model's amount-free boundary applies: qualification verdicts cross, dollar amounts never do |
| **Billy** (the Benefits Investigation Platform) | into Pulse           | The upstream source of benefits and eligibility verdicts that reach Pulse through the warehouse mart — lineage being formally confirmed                                      |
| **Twenty** (the care-team board)                | both                 | Card drags come in through the signed webhook door; the board's contents are painted back from the ledger by the projection                                                  |
| **The legacy backend and its databases**        | into Pulse, one-time | The migration source: Pulse's genesis will reconstruct each patient's history from the legacy systems, after which they stop being sources of truth                          |
| **Customer.io** (patient messaging)             | into Pulse           | Consent opt-ins and opt-outs land in the warehouse and are swept into the ledger as attributed consent state                                                                 |
| **AWS** (cloud infrastructure)                  | underneath           | The event bus and queues are managed Amazon services — Pulse rents the public-address system rather than building one                                                        |


The dependency rule that keeps this healthy: anything not on a published surface is private,
and no team integrates by copying another team's code or reading another team's database.

## 5.0 Where the project stands

- **Phases 0–2 complete** — the event transport, the ledger core, and all four sanctioned
fact sources (board drags, consent, identity, verdicts) shipped and archived; version 2.0
released 2026-08-08.
- **Phase 3 complete** — the Twenty board projection, the warehouse feed, the billing/coverage
pairing, and the rebuild drill (destroy a view, rebuild it from the journal, prove it
identical — the one-patient walk's closing stage) all shipped and proven, offline and live.
Two items remain chosen, not invented: retiring the legacy backend's direct patient-state
writes so the ledger's projection is the only writer, and building the Customer.io projection
(syncing patient segments and attributes out of the ledger, so messaging targets current
truth).
- **The connector kit shipped and archived** (`connector-pattern`, 2026-09-02). Any system
that wants to write billing-adjacent state now builds on one shared package instead of forking
the pattern — the kit itself, plus the billing engine's scaffold, its fact-folding, and its
ported eligibility rules, are on `main`. The work was cut at a clean seam: everything
downstream of "which verdict types exist," which turned out to be a billing question and not
a ledger one, moved to a seeded follow-on change.
- **The Billing Connector is seeded, not yet started.** It inherits the six tasks that write
billing state, deploy the engine, and retire the verdict relay's direct Snowflake read, plus
three entry gates the connector-pattern work surfaced: a committed dbt source for each rule
module the billing engine evaluates, the pinned spike files landing durably on a
`data-platform` branch, and the review-queue filter breadth decided. Its proposal is drafted;
it has not been dispatched.
- **Then**: Phase 4 retires the warehouse's inferred-state models in favor of ledger reads,
and the genesis-and-cutover ladder migrates real patient history in, with rehearsals and
receipts at every step.

**Next step for this audience:** if you want to see it rather than read about it, any engineer
can run the one-patient walk in about five minutes (`task demo:e2e`) — or watch it live
against the development board in an attended session.
