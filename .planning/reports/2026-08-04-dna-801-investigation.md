# DNA-801 investigation: wire pulse_ledger.api to idempotent commit

Read-only investigation. No edits made.

## 1. Where the gap actually is

**HTTP layer** — `packages/pulse-ledger/src/pulse_ledger/api.py`:
- `Committer` type (`api.py:78`) is `Callable[[Declaration], CommitResult]` — one arg, no key.
- `_DECLARATION_FIELDS` (`api.py:106`) + `coerce_declaration_fields` (`api.py:192-216`, unknown-field
  check at `198-202`) has no allowance for `idempotency_key`, so a body carrying it 422s as an
  unknown declaration field.
- `_commit_response` (`api.py:230-247`) builds the response dict and never reads `result.replayed`.
- `submit_command` (`api.py:399-407`) calls `committer(declaration)` directly — never
  `commit_idempotent`.

**Commit layer already supports both halves**, unused by the HTTP path:
- `pulse_ledger.idempotency.commit_idempotent` (`idempotency.py:59-89`) takes
  `idempotency_key` as a required kwarg, claims it in the same transaction as the event, and
  returns `CommitResult(replayed=True)` on replay via `_replay_of` (`idempotency.py:100-126`).
- `CommitResult.replayed: bool = False` already exists (`commit.py:213`).
- `packages/pulse-ledger/tests/test_idempotent_commit.py` fully covers `commit_idempotent`
  against real Postgres — the commit-layer half of D16 is proven, only unreachable from HTTP.

**Client already assumes the fix landed**:
- `pulse_core/client.py:129-163` (`classify_response`) reads `mapping.get("replayed", False)` —
  today always `False`, so every replay classifies `committed` (this is the literal DNA-801 bug).
- `pulse_core/client.py:300-307` (`submit_command`) always sends `idempotency_key` in the body —
  today always rejected... no, actually accepted-and-ignored since it's dropped as unknown only if
  `coerce_declaration_fields` rejects unknown keys, which it does today (422). So today, any real
  `PulseCoreClient.submit_command` call against the live API would 422 on every request, not just
  misclassify — a stronger break than the docstrings emphasize.
- `client.py:19-23` module docstring names this exact gap and says it was "recorded in HANDOFF.md
  rather than patched here" by whichever task built `pulse_core` — it isn't `pulse_ledger`'s
  package.

## 2. Concrete change list (the real diff)

All within `packages/pulse-ledger/` — `pulse_core` needs no change, it already assumes the fixed
contract.

1. `api.py` — extend `Committer`'s contract to carry the key through. Cheapest shape: change
   `Committer` to `Callable[[Declaration, str | None], CommitResult]` (or a small dataclass/kwarg),
   since no production entrypoint exists yet that constructs a real committer (task 4.5 / the
   service entrypoint is not present in the tree — every current caller is a test fake).
2. `api.py` — carve `idempotency_key` out of the body before `coerce_declaration_fields`'s
   unknown-field check (it is not a `Declaration` field, so it must be extracted, not merged in
   like `occurred_at`/`rule_version`).
3. `api.py` — `submit_command` (and `submit_command_batch`) pass the extracted key to `committer`.
4. `api.py` — `_commit_response` adds `"replayed": result.replayed`.
5. `packages/pulse-ledger/tests/test_api_auth.py` — `FakeCommitter.__call__` (`~line 58`),
   `FailingCommitter` (also in `test_api_cursor.py:33`), and the inline lambda at
   `test_api_auth.py:291` all take one positional arg today; each needs the new signature. Add new
   scenarios: idempotency_key accepted, `replayed: true` echoed on a repeat key, missing/duplicate
   key behavior (spec doesn't currently say whether the key is mandatory at the HTTP layer —
   flagged as an open question below).
6. Doc follow-up, not code: `docs/contracts/publishes.md:45-52` and `pulse_core/client.py:19-23`
   both carry "known gap" prose naming DNA-801 by number — these read as stale once the fix lands
   and should be removed/updated in the same PR. ADR-0003's Consequences section names the gap as
   a past-tense fact ("Known gap, tracked...") — ADRs are append-only per repo convention, so this
   is left as historical record, not edited.

Rough size: ~4 focused edits in one file (`api.py`, maybe +40-60 lines net incl. the extraction
helper), test-fake signature updates in 2 files (~6 call sites), a handful of new test cases
(~60-100 lines), two doc-paragraph deletions. No new files, no schema change, no new OpenSpec
capability — this is closing an implementation gap against a requirement the baseline spec already
states.

**Open question for whoever implements**: is `idempotency_key` mandatory at the HTTP boundary
(reject its absence, matching the spec's "Every command SHALL carry..."), or optional-for-now
(accept-if-present) to avoid breaking any caller that predates this fix? No current caller sends
one except `pulse_core.client`, and no batch-mode caller (`test_backfill.py`) supplies one either —
worth a decision-gate question if this proceeds, not something to guess.

## 3. What the docs already say (constraints, not just context)

- **`openspec/specs/command-api/spec.md:35-53`** — "Requirement: Commands are idempotent by
  client-supplied key" is already in the accepted baseline (landed by the archived
  `pulse-ledger-core` change, DNA-784) with two scenarios: retry-after-timeout replays, distinct
  logical-time never shares a key. **This means DNA-801 needs no spec delta** — the spec already
  SHALLs the behavior; the HTTP layer is simply non-compliant with an already-accepted spec. That
  is a bug fix, not a new capability.
- **`docs/adr/ADR-0003...md`, Consequences** — names the gap explicitly, says "The fix is small and
  server-side: accept `idempotency_key` in `coerce_declaration_fields`, thread it to
  `commit_idempotent`, and add `"replayed": result.replayed` to the response" — matches the change
  list above almost exactly, and states `s12-verdict-relay` "must not build on it" until DNA-801
  lands.
- **`docs/contracts/publishes.md:45-52`** — same gap, same instruction: "Do not depend on the
  `replayed` classification, and do not send `idempotency_key` over HTTP, until DNA-801 lands."
- **`openspec/changes/s12-verdict-relay/design.md:14-19`, `proposal.md:11-15`, `tasks.md:7-10`** —
  s12 already exists as an in-planning OpenSpec change (proposal/design/specs/tasks all written,
  not yet dispatched) that explicitly treats DNA-801 as an *external entry condition*, not one of
  its own tasks: "this change SHALL NOT be dispatched for execution before DNA-801 lands. Planning
  artifacts are [unaffected]." s12 is scoped to `pulse_core`/verdict-relay consumption of the
  command API, not to `pulse_ledger` internals — it doesn't touch `api.py` or `idempotency.py`
  anywhere in its own task list.

## 4. Option comparison

**(a) New OpenSpec change (`ledger-idempotency-wiring` or similar), full loop.**
- Pro: fits the repo's default process; produces its own tasks.md checklist and Linear sub-issues.
- Con: no new spec requirement exists to write — the spec delta would be empty or vacuous, since
  `command-api/spec.md` already states the target behavior. OpenSpec changes are for *deciding*
  something; there's no decision left to make here, only an implementation gap to close, already
  fully diagnosed in ADR-0003 and `publishes.md`. Propose→validate→dispatch→sync_linear→execute→
  collect→verify→archive ceremony for a ~150-line, single-package diff is disproportionate — this
  is exactly the class of overhead `main_access`'s "mechanical state update" carve-out exists to
  avoid duplicating, just one layer up.

**(b) Fold into `s12-verdict-relay` as a wave-0 task.**
- Con, not recommended: wrong ownership. s12's own design/proposal/tasks docs already describe
  DNA-801 as something s12 *waits on*, written by a different package boundary
  (`pulse_ledger` vs. `pulse_core`/verdict-relay). Folding it in means: (1) rewriting three s12
  planning docs that currently say "not our task, it's an entry condition" into "our task", (2) a
  PR/review that mixes two packages' concerns and two different reviewers' natural scope, (3) if
  DNA-801 needs escalation or a design change independent of s12's own schedule, it's now stuck
  inside s12's wave sequencing instead of shippable on its own. s12 also cannot be dispatched until
  DNA-801 lands per its own design.md — sequencing DNA-801 as its wave 0 would work mechanically,
  but couples an unrelated bugfix's review to verdict-relay's, for no benefit.

**(c) Direct fix PR outside OpenSpec.**
- Pro: matches what this actually is — implementation catching up to an already-accepted spec
  requirement, isolated to one package, already fully scoped by ADR-0003 and publishes.md down to
  the function-level fix. `main_access` still requires a PR (touches `src/`) — this isn't a
  bypass-review shortcut, it only skips the OpenSpec proposal/design/tasks ceremony that has
  nothing left to decide. `AGENTS.md`'s "specs are owned by the doc-updater, never edit spec files
  directly" doesn't bind here either, since no spec file changes — `command-api/spec.md` is
  already correct.
- Con: doesn't get a Linear sub-issue or tasks.md checklist automatically the way a dispatched
  change would; whoever picks it up should still open a Linear issue/PR manually and link DNA-801,
  and update the two "known gap" doc paragraphs in the same PR so they don't go stale.

## 5. Recommendation

**Option (c): direct fix PR**, scoped to `packages/pulse-ledger/` only (api.py + its two test
files), plus deleting the two stale "known gap" paragraphs in `pulse_core/client.py`'s docstring
and `docs/contracts/publishes.md` in the same PR. Rationale: the target behavior is already an
accepted spec requirement (`command-api/spec.md:35-53`, landed by the archived
`pulse-ledger-core` change) — there is no design decision left to make, so a full OpenSpec change
would produce ceremony with no spec delta to show for it. Folding into s12 is the wrong package
boundary and couples an independent bugfix's review to verdict-relay's own schedule, contradicting
what s12's own planning docs already say about DNA-801 being external to it. A direct PR still goes
through the normal PR/CI gate `main_access` requires — nothing here proposes skipping review, only
skipping the proposal stage that has nothing left to propose.

One decision worth a human call before implementing: whether `idempotency_key` becomes mandatory
at the HTTP boundary (matching the spec's "SHALL carry") or accepted-if-present. Recommend asking
via `orca orchestration ask` / a decision gate on the PR itself rather than guessing.
