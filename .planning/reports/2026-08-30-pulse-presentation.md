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

## 3.0 The features, proven by the demos

Each demo is a script anyone can run. It performs real actions and stops with a failure if
any promise is broken. All four pass as of 2026-08-30.

### 3.1 Demo 1 — the record keeps honest books

Runs the whole system on a laptop. It proves four things: a legal state change is accepted
and announced on the bus; an illegal one is refused with the exact rule that forbids it (and
the rulebook version); submitting the same change twice returns the original receipt with no
duplicate; and an independent re-reading of the whole journal lands on exactly the same
current answer the ledger keeps. **Translation: the books balance, and cheating is refused
with a reason.**

### 3.2 Demo 2 — the doors check identity and credentials

Two offline legs. The identity leg shows how a new referral is matched to an existing
patient: an exact identifier match wins, an unknown patient is created, and any ambiguity —
two plausible candidates, or two identifiers pointing at different people — is quarantined
for a human instead of guessed at. The kanban leg shows the board's webhook door: a properly
signed card move commits, an illegal move is refused and the mover gets a comment on the card
explaining why, and a tampered signature is turned away entirely. **Translation: nobody gets
merged by a guess, and nothing enters the ledger without checked credentials.**

### 3.3 Demo 3 — the care-team board is a window, not a copy

Runs against the real development environment: a real Twenty board (the care team's kanban
tool) and the real ledger, live. Nine assertions, including: the board's columns are exactly
the rulebook's states; dragging a card through a legal move becomes a ledger entry; dragging
it through an illegal move is rejected, the card snaps back, and one explanatory note appears;
and replays produce no second entry. **Translation: the board the care team touches is a live
window onto the ledger — moving a card is declaring a fact, and the rulebook applies to
humans too.**

### 3.4 Demo 4 — billing and coverage become continuously known

Also live. Brook's analytics pipeline computes verdicts — "this billing episode is eligible,"
"this patient's insurance is active." Pulse's relay reads each verdict and, for registered
verdict types, files both the evidence and its consequence: the verdict entry plus the state
change it justifies. A verdict for a patient-and-payer pair Pulse has never seen creates the
coverage subject on the spot. An immediate re-run changes nothing. A verdict whose
consequence is no longer legal (the episode already moved on) keeps the evidence and skips
the state change, counted and explained. **Translation: "is this billable, is this covered"
stops being a question each team answers by spreadsheet — it is a state Pulse continuously
knows.**

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
- **Phase 3 nearly complete** — the Twenty board projection, the warehouse feed, and the
billing/coverage pairing all shipped and proven live. The remaining Phase 3 work is
chosen, not invented: the rebuild drill (destroy a view, rebuild it from the journal,
prove it identical), retiring the legacy backend's direct patient-state writes so the
ledger's projection is the only writer, and building the Customer.io projection (syncing
patient segments and attributes out of the ledger, so messaging targets current truth).
- **Then**: Phase 4 retires the warehouse's inferred-state models in favor of ledger reads,
and the genesis-and-cutover ladder migrates real patient history in, with rehearsals and
receipts at every step.

**Next step for this audience:** if you want to see it rather than read about it, any
engineer can run Demo 1 on a laptop in about two minutes — and Demo 3 will move a real card
on the development board in front of you.