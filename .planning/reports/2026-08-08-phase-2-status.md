# Phase 2 (Ingress) status — 2026-08-08

## 1. Executive summary

Phase 2 of the PULSE program ("Ingress") is about making sure every change to a patient's state
in the system happens through one governed, auditable path instead of scattered, unchecked
writes. Six of the phase's seven planned changes are now shipped: patient-identity matching,
scheduled billing and consent jobs, a verdict-relay service, an authoritative state catalog, a
working kanban-to-ledger integration with Twenty, and — as of today — a CI gate that
automatically blocks any code from asserting patient state outside that governed path. The
seventh and last change, bringing Customer.io consent data onto the same governed path, is
waiting on an organizational decision (which team owns compliance sign-off and how the data
export works), not on engineering. Once that decision lands and the change ships, Phase 2 is done
and the program moves to v2.0.

## 2. Shipped

| Change | What it delivers | Archived |
|---|---|---|
| Verdict relay | Automated relay of computed outcomes into the ledger | 2026-08-05 |
| Schedules | Automated monthly billing opens + daily consent reconciliation | 2026-08-06 |
| Identity matching | Deterministic patient-identity resolution | 2026-08-06 |
| Catalog authority | The state catalog as a versioned, published contract | 2026-08-07 |
| Kanban webhook ingress | Kanban board drags become governed state changes | 2026-08-08 |
| Producer-ingress policy | CI gate blocks ungoverned patient-state writes | 2026-08-08 |

### 2.1 Verdict relay

Clinical and business rules get computed in the data warehouse (dbt), but until now nothing
carried those results back into the ledger — that loop was open. This change closes it: a new
service reads computed verdicts and writes each one to the ledger as a proper, attributed command,
resuming safely if it crashes partway through and never double-counting a result it already
recorded. It also retires an older, never-built plan to write verdicts a different way, so there
is now exactly one path for verdicts to reach the ledger. Runbook: `docs/runbooks/verdict-relay.md`.

### 2.2 Schedules

Two jobs that used to have nobody driving them now run on a clock: opening a billing period for
every active patient enrollment at the start of the month, and reconciling communication consent
daily against Customer.io's records (Customer.io wins any disagreement). Both are safe to re-run
— accidentally running twice just confirms what already happened rather than duplicating it — and
both fail loudly rather than quietly reporting success on bad or missing data. Runbooks:
`docs/runbooks/month-open.md`, `docs/runbooks/consent-sweep.md`.

### 2.3 Identity matching

The system can now decide, deterministically, whether an incoming referral is a patient already
known to us or a new person — and if it's ambiguous, it routes to a human reviewer rather than
guessing. This matters because a wrong auto-merge in a healthcare system is a reportable incident,
so the matcher never scores probabilities or auto-resolves uncertainty; it only ever returns a
clean match, a clean new person, or "send this to a person." Patient demographics never reach the
ledger — only a one-way hash of the matching fields does. This matcher is now a stable, published
building block other parts of the program (and a future historical-data migration) will reuse
rather than rebuild. Reviewer runbook: `docs/runbooks/identity-quarantine.md`.

### 2.4 Catalog authority

The "rulebook" that says which patient states exist and which transitions between them are legal
— previously a placeholder seed file — is now the authoritative, versioned source of truth,
published from git and released into Snowflake as an appendable, versioned record. A
breaking change (removing a state, narrowing an allowed value, or changing what transition is
legal) now requires a version bump and a written migration note, checked automatically. This is
the contract the next change (the CI gate) checks producer code against. Runbook:
`docs/runbooks/catalog-release.md`.

### 2.5 Kanban webhook ingress

Dragging a card on the Twenty kanban board now does something real: it becomes a governed,
signed, attributed command on the ledger, validated against the same rules every other change to
patient state goes through. Drag something into an illegal state and the system rejects it and
posts a comment back on the card explaining why, instead of silently letting the board and the
ledger disagree. The request is authenticated so it can't be spoofed, and the signing secret
rotates on a schedule without downtime. (Moving the card back to reflect the *true* state after a
rejection is a follow-on piece of work, not yet built.) Runbook: `docs/runbooks/twenty-webhook.md`.

### 2.6 Producer-ingress policy

The governed-path rule is now permanent and automatic, not just convention: no code anywhere in
the legacy `ocean` producer layer can assert a patient-state change on its own — it has to go
through the ledger's command path instead, or the build fails and names exactly what it doesn't
like. A reviewed false positive (ordinary code that happens to share a word with a patient-state
name) gets a justified, on-record suppression, and a suppression that goes stale automatically
fails the check rather than quietly living forever. This is the last piece of engineering work
Phase 2 needed. Shipped 2026-08-08.

## 3. Nothing currently in flight

All engineering work for Phase 2 is shipped. The only outstanding change,
`customerio-consent-ingress`, is not in execution — it is waiting on an organizational decision
(export mechanism + a compliance owner), covered in Section 6.

## 4. Docs and contracts delivered this phase

- `docs/contracts/publishes.md` — what this repo now guarantees to other teams: the ledger's
  write/read API, the identity matcher, the state catalog, and the Twenty webhook route.
- `docs/contracts/consumes.md` — what this repo depends on from elsewhere: the dbt verdict output
  and the Twenty comment API (the latter is a documented best guess, not yet checked against a
  live Twenty instance — that check happens in the next phase).
- ADR-0004 (`docs/adr/ADR-0004-runtime-readiness-decisions.md`, accepted 2026-08-06) — five
  standing decisions closed together: where PULSE services run, how the Twenty webhook
  authenticates, and that Snowflake is the system of record for the catalog.
- Runbooks shipped this phase: `verdict-relay.md`, `month-open.md`, `consent-sweep.md`,
  `identity-quarantine.md`, `catalog-release.md`, `twenty-webhook.md`, plus a partial Demo 2
  writeup, `demo2-partial-s13-s14.md`.
- `design/delivery/pulse-program-roadmap.md` — the program's status tracker, refreshed after each
  change closes.

## 5. What we can demo today

Demo 2 is the phase's proof point — a short, offline, no-credentials walkthrough showing that
patient-state changes now flow through the governed path, with rejections handled honestly. It has
five legs. Four are demoable right now; the fifth (Customer.io) waits on the same organizational
hold as the rest of that change.

**Demoable now:**

1. **Identity resolution** — an exact match, a new-person mint, and a two-candidate quarantine,
   each with its reasoning printed. Run: `uv run python scripts/demo/demo2_identity_matcher.py`.
2. **Month-open and consent sweep** — the would-do list for a normal month, the forced failure on
   zero enrollments, and consent corrections in both directions. Covered in the partial Demo 2
   receipt (PR #144, `docs/runbooks/demo2-partial-s13-s14.md`).
3. **Kanban drag → committed transition, and invalid drag → rejection** — a signed, synthetic
   card drag commits end to end; an illegal drag gets rejected with a reason and a comment posted
   back to the card; a tampered signature is rejected before any processing happens. Shipped in PR
   #165. Run: `uv run python scripts/demo/demo2_kanban_drag.py`.
4. **The CI gate going red, then green** — the gate now runs as part of the standard build
   (`task check`), and its own test suite (`tests/test_producer_ingress_policy.py`) rehearses the
   exact mechanic: plant a rule-breaking emit in a scratch copy of the producer tree, watch the
   check fail naming the offending file and the patient state it collides with, then remove it and
   watch the check pass again. Shipped in PR #173.

**Not yet demoable:**

5. **A consent fixture recorded with actor `customer.io`** — waits on the `customerio-consent-ingress`
   change, which is itself waiting on the same organizational decision described above.

## 6. Remaining to phase exit

- **Resolve the Customer.io hold.** This is the only item left, and it isn't an engineering task —
  it needs an export-mechanism decision and a compliance owner assigned. It's also the last of the
  four command sources the phase needs live.
- **Complete the Demo 2 receipt.** Once that hold clears and the change ships, the one missing leg
  (the Customer.io consent fixture) folds into the existing receipt for one full walkthrough.
- **Phase-exit bar, in plain terms:** no code anywhere can quietly change a patient's state
  outside the ledger's governed path (enforced automatically by CI), and all four approved ways of
  writing state — the kanban board, the identity service, the verdict relay, and Customer.io — are
  live and demoed.

## 7. Risks and notes

- The only thing left in Phase 2 is a decision that depends on people outside this repo's control
  (a compliance-owner role-fill for the Customer.io export). No engineering work is blocking it.
- The review fix to the CI gate's matching rule landed in the same pull request as the original
  proposal rather than as a separate correction — worth a quick check that the written design
  doc reflects the corrected rule now that the gate is live and enforcing in `task check`.
- A couple of open loose ends from earlier changes (board-vocabulary alignment between Twenty and
  the catalog, and some catalog fields not yet fully filled in) are tracked on their parent
  tickets rather than showing up as open tasks in the archived changes — worth keeping an eye on
  so they don't get lost.
- The Twenty comment integration is a documented best guess, not yet checked against a real
  Twenty instance. That check happens in the next phase; if the real API shape differs, only the
  small client module needs to change, but it's worth flagging as an unverified assumption today.
