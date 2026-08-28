# repo-ade Dispatch Template — Work-Order Format v1

**Status:** Draft v1.0 — for adoption into the repo-ade scaffold | **Deciders:** Ford
**Scope:** The file format `task dispatch` emits per task into `work_orders/<change>/`, merging the five-field work-order contract with OpenSpec artifacts, the model router, and escalation policy. Plus the `tasks.md` declaration conventions dispatch parses, the routing rubric, the HANDOFF contract, and the Orca hardening checklist that gates Brook repos entering the ADE.
**Home:** `repo-ade/templates/work-order.md` (the template), `repo-ade/docs/dispatch.md` (this document). WORKFLOW.md Phase 3 references both.

---

## 0. TL;DR

One work order = one task = one worktree = one commit. The dispatched file is a self-contained prompt: an agent with the worktree and this file needs zero clarifying questions, and a CI exit code — not judgment — decides acceptance. Two fields are new to the format: `model` (router-declared, attributed in every receipt) and `escalation` (the failure ladder that replaces fan-out). Routing follows verifier strength, not task prestige. The HANDOFF carries spec-relevant deltas only, plus the model/attempt receipt. Nothing enters Orca until the Appendix A hardening checklist clears.

---

## 1. The dispatched file

`task dispatch --change <change>` emits one file per task: `work_orders/<change>/<task-id>.md`. Exact shape:

```markdown
---
change: add-jwt-auth
task: task-003
title: Token refresh endpoint
model: sonnet                # router-declared: sonnet | opus | fable
escalation:                  # the failure ladder
  max_tier: opus
  attempts_per_tier: 2
depends_on: [task-001]       # dispatch wave gating — must be merged first
parallel_safe: true          # false forces serial dispatch (see §4)
spec_refs:
  - openspec/changes/add-jwt-auth/specs/auth/spec.md#token-refresh
scenarios: [S-07, S-08]      # Given/When/Then IDs this task must satisfy
---

## Context
Package: <path>. Depends on: <task IDs + what they provide — module paths,
schema names, never "see the other task">.
Read AGENTS.md first, then call orient("<task description>") via OpenLore MCP,
then read the spec_refs above. <External constraints, API quirks, links.>
Rule: if the agent would need to rediscover it, it is written here.

## Task
1. <path> — <behavior>
2. <path> — <behavior>
n. tests/<path> — <named test types, fixtures, prohibitions: NO live
   network calls, socket-blocking fixture active>
Write tests first (red-green-refactor). One task = one commit.

## Out of scope
- <Adjacent temptation> (that's <task-id>)
- <Adjacent temptation> (that's <task-id> / next change)
Minimum two entries. This is the semantic-conflict guard for parallel
worktrees — name what a helpful agent would build and must not.

## Verification
task lint && task test
<change-specific commands with checkable exit codes — golden files,
property tests, schema round-trips named in Task, never prose criteria>

## Done means
<Terminal state readable from the diff and CI alone.> Plus, always:
HANDOFF.md written per §5, single commit, worktree pushed,
PR opened against main ready for review (never --draft), CI checks green.
```

Field-by-field semantics where they differ from the classic five-field contract:

- **Context** absorbs what Linear-era orders spelled out by hand. AGENTS.md is the operating contract, `orient()` is the knowledge-graph read, `spec_refs` are the requirements of record. Context still states anything not discoverable through those three — discoverable-in-principle is not the bar, zero-rediscovery is.
- **Task** items are file-level or they are defects. Test artifacts are Task items, not afterthoughts.
- **Out of scope** does double duty in the parallel world: collision guard against sibling tasks in the same wave, and drift guard against the next change. Both entries cite an ID.
- **Verification** must pass the tier-adjusted gaming pass (§3). `task lint && task test` is the floor, never the whole gate for anything non-trivial.
- **Done means** is what the human reads at Phase 8 merge review. If it cannot be confirmed from the diff, CI checks, and HANDOFF alone, it is misfiled Context. It always terminates at a green, reviewable PR, never a local commit: the reviewer reads a PR, so work that stops before one has not reached the step that consumes it. Draft counts as not-reached — it withholds finished work while reading as still-in-progress.

## 2. tasks.md declaration conventions

Dispatch parses these from the change's `tasks.md`. Per task, one header block:

```markdown
### task-003 — Token refresh endpoint  [model: sonnet | max: opus | deps: task-001 | parallel: yes | scenarios: S-07, S-08]
```

Two further keys come from WORKFLOW.md v2's `lanes` block, and a GitHub-flavored checkbox list carries the same annotations inline:

```markdown
- [ ] 2.1 Emit the topic mapping  [model: opus | deps: 1.3 | lane: repo_change | wave: 1]
      `serial: catalog_generated_surfaces` — producers and rules both derive from it.
```

`serial: <reason>` is an accepted spelling of `parallel: no` that carries its own justification, which is what the MECE check wants anyway.

Defaults when omitted: `model: sonnet`, `max: opus`, `attempts_per_tier: 2`, `parallel: yes`, `deps: none`, `lane: repo_change`. A task with no annotations at all is therefore an ordinary parallel repo-change task — an unannotated `tasks.md` dispatches exactly as it did before these keys existed.

The Phase 2 MECE check extends by three assertions: every task declares or defaults a model, every dependency edge names an existing task, and every `parallel: no` task states why in its body (almost always: touches a generated surface or a shared root file).

**`lane` is enforced, not advisory.** `scripts/dispatch_tasks.py` writes no work-order file for a task in an excluded lane. This is the one annotation whose absence is dangerous rather than merely untidy: a `destructive_ops` task without its lane declared becomes an ordinary work order, and an Orca agent will pick up a production teardown. Declare the lane on anything that has no reviewable diff.

**`wave` is a label, and the graph is the truth.** Dispatch derives release order from `deps` alone. A declared `wave` is cross-checked for one property — nothing may sit in a wave earlier than something it depends on — and is otherwise documentation. It is deliberately coarser than dependency depth: one wave may contain an ordered chain, and `2a`/`2b`/`2c` split a single depth into human-sized releases.

## 3. Routing rubric — verifier strength, not task prestige

The router assigns the *starting* tier. The rubric:

| Route to | When |
|---|---|
| **sonnet** | The verifier is strong enough that a wrong implementation cannot pass: golden files, property tests, schema round-trips, conformance-by-inheritance work, mechanical fixes, generated-surface regeneration (serial, per §4) |
| **opus** | Judgment inside one package: ambiguous refactors, tasks carrying a deferred-judgment escape hatch, pattern-inheritance work where the source pattern must be read correctly |
| **fable** | Where spec quality gets set, so errors compound downstream: Phase 1 propose, Phase 2 MECE review assist, Phase 6 doc-updater, catalog-touching changes, evidence adjudication |

Two rules ride along:

- **Tier-adjusted gaming pass.** Read Verification as an adversary *at the assigned tier*. A weaker model finds the lazy artifact faster — if the laziest thing that passes isn't the thing you want, strengthen the commands or route up. Do one, not neither.
- **Weak verifier → fix the verifier first.** Routing up to compensate for prose criteria is buying judgment to paper over a spec defect. The escalation ladder exists for genuine difficulty, not for unverifiable acceptance.

## 4. Dispatch mechanics: waves, serial lanes, escalation

**Waves.** Dispatch releases only tasks whose `depends_on` are merged. Orca will happily parallelize a dependency chain if allowed — the wave gate is what stops it. Within a wave, everything `parallel: yes` may run concurrently in separate worktrees. "Merged" is read off `tasks.md`: a checked box is a merged task, so checking one off is the act that opens the next wave — and `task checkoff CHANGE=<id>` is the normal actor for that flip, deriving it from merge subjects' `(X.Y[, TEAM-n])` tag rather than a hand-typed commit. The subject tag is therefore normative: dispatch writes the task id into the work-order title, the PR title inherits it, and checkoff reads it back. Hand-flipping stays legal under `main_access`; it is just the slow way.

A dependency on an out-of-lane task holds its dependent exactly like any other, and dispatch names the lane when it reports the block. That work is real; it simply happens on another queue.

**Serial lane.** `parallel: no` tasks run alone — nothing else from the change in flight. Standing members of the serial lane: anything regenerating catalog surfaces (Twenty metadata, FSH, warehouse seeds, command types), anything editing workspace roots (`pyproject.toml`, CI config, pre-commit), anything touching AGENTS.md or the OpenSpec main specs. These merge clean and disagree semantically — the exact anti-pattern the research flagged — so they never share a wave.

**Escalation.** On verification failure at attempt `attempts_per_tier`, redispatch at the next tier in a **fresh worktree** with the identical work-order file plus one appended section:

```markdown
## Escalation context
Attempt 1–2 at sonnet failed verification. Failing output: <verification
excerpt>. Prior worktree branch: <ref, read-only>. Do not resume the prior
session — diagnose fresh, the prior attempt's framing may be the defect.
```

Ceiling is `max_tier`. Failure at ceiling is a spec defect by definition: the task returns to Phase 2, not to a bigger model. Every attempt is a receipt — tier, attempt number, verification result — carried in the HANDOFF and visible at merge review. This ladder is the replacement for fan-out: one implementation to review, premium tokens spent only where the cheap tier demonstrably failed, and Orca's usage tracking tells you whether the ladder pays.

**Fan-out remains sanctioned for exactly one class:** exploratory work with no single correct answer (UI treatments, design alternatives), where comparing N diffs is the point. Never for spec-determined tasks — that is N× cost plus review debt for one verifier-defined answer.

## 5. HANDOFF.md contract

Required from every worktree, spec-relevant content only:

```markdown
# HANDOFF — <change>/<task-id>

## Receipt
model: sonnet | attempt: 1 | tier_history: [sonnet:1]
verification: pass | commit: <sha>

## Spec deltas
<Requirements added / modified / removed that Phase 6 must fold into
specs/. Empty section stated as "None." Implementation details are
prohibited here — they live in the diff.>

## Design Drift            # include only if hit — and then STOP
<The contradiction between spec and reality, stated neutrally. Work
halted at this point per WORKFLOW.md decision table.>

## Deferred judgment       # include only if non-empty
<Choices requiring a behavior call the order didn't license, listed
not guessed.>
```

The Receipt block is the router's attribution surface — same doctrine as the ledger's actor field. Phase 5 `task collect` aggregates receipts into SUMMARY.md so the change's tier economics are readable in one place — and `handoffs/<change>/SUMMARY.md` is **tracked** (WORKFLOW v2.1.0): a receipt record that lives only on one workstation is not a record, and whether the escalation ladder pays is unanswerable without it. The tracked summary inherits the HANDOFF content rule with teeth: receipts and spec deltas only, no operational detail, no PHI — a violation is a review-reject, and `task collect` refuses outright when the summary path is gitignored.

## 6. Quality gate before dispatch (per work order)

1. Zero-rediscovery: could the assigned tier execute with the worktree and this file alone?
2. Every criterion an exit code — rewrite or delete prose criteria.
3. Out of scope names two adjacent temptations with IDs.
4. One session, one package, one commit — split if not.
5. Tier-adjusted gaming pass done at the *assigned* model, and again at `max_tier`'s floor if they differ.
6. `parallel` flag honest — serial-lane membership checked against the standing list in §4.

---

## Appendix A — Orca hardening checklist (gates Brook repos entering the ADE)

Run once per workstation, receipt the results on a Linear issue before any brookai repo gets a worktree. Re-run on version bumps.

| # | Check | Pass condition |
|---|---|---|
| H1 | Telemetry | Opt-out flag set, then verify by observation: no analytics egress in a network capture during a full worktree lifecycle |
| H2 | Daemon binding | Listener bound to localhost only — confirm with a socket inspection, not the docs |
| H3 | Version pin | Auto-update disabled, version pinned, upgrades deliberate (daily-release churn does not reach a HIPAA workstation unreviewed) |
| H4 | Agent permission defaults | Launch flags inspected — no permission-bypass or auto-approve defaults active for Claude Code sessions Orca spawns |
| H5 | Credential isolation | No prod credentials in worktree env or Orca config. Secrets resolve at runtime from the DuploCloud store via the archaeology-package pattern. BF-0b-class prod reads stay outside Orca until H1–H4 hold |
| H6 | Config integrity | Agent config files (~/.claude and equivalents) checksummed before and after a multi-agent session — verifies the unreproduced cross-agent-mutation report doesn't manifest locally |
| H7 | Worktree hygiene | Spent worktrees deleted at Phase 8 as a checklist step, not a memory burden — idle worktrees are RAM and stale-branch drift |

H1–H4 are the adoption gate. H5 is standing policy. H6–H7 are per-session discipline.

**Enforced at dispatch.** `scripts/dispatch_tasks.py` refuses to release work orders unless
`.orca/hardening-receipt.json` records H1–H4 all `pass` and is under 90 days old. The receipt is
per-workstation, so `.orca/` is gitignored and the gate is never satisfied by inheriting someone
else's file. `unverified` blocks exactly as `fail` does — a check nobody could complete is not a
check that passed.

```json
{
  "workstation": "<name>",
  "audited": "YYYY-MM-DD",
  "issue": "https://linear.app/.../DNA-777",
  "checks": {"H1": "pass", "H2": "pass", "H3": "pass", "H4": "pass",
             "H5": "pass", "H6": "pass", "H7": "pass"}
}
```

H4 is additionally checked **live**, against `settings.agentDefaultArgs` in Orca's profile store,
because a receipt records what was true when someone looked and that one setting silently re-arms
every worktree afterwards. Orca ships a bypass default for all 24 agent types it knows —
`--dangerously-skip-permissions`, `--yolo`, `--trust-all-tools` and so on — so this is a default
to be turned off, not an accident to be spotted. A live bypass blocks dispatch even with a clean
receipt.

### Accepted exceptions

Some checks cannot pass without giving up something genuinely wanted. H2 asks for a localhost-only
daemon; the Orca mobile client needs the daemon reachable. There is no configuration that satisfies
both, so pretending otherwise would mean either a false `pass` or `--skip-hardening` on every
dispatch — and an exception you take every single time stops being a decision and becomes noise.

A check may therefore be `accepted` instead of `pass`, if the receipt carries a matching entry:

```json
"checks": {"H2": "accepted"},
"exceptions": {
  "H2": {
    "justification": "why this cannot pass, and what compensates for it",
    "review_by": "2026-11-02",
    "accepted_by": "Ford"
  }
}
```

Both fields are load-bearing. An exception with no justification blocks; an exception with no
`review_by`, or a lapsed one, blocks. **An exception that never expires is a silent failure with
better manners.**

`accepted` cannot launder the live H4 check. That one is read from Orca's actual settings at
dispatch time, so no amount of paperwork makes a live bypass releasable.

`--skip-hardening` releases anyway and prints what was skipped. With `accepted` available it
should be rare — reach for it when the gate itself is wrong, not when a check is inconvenient.
Tests that exercise work-order emission rather than release also use it.

This was added because the gate had been declared in `WORKFLOW.md` and enforced by nothing: two
worktrees were released straight through it, and the audit that followed (DNA-777) found every
agent launching with permissions off.

---

## Change log

**v1.0 (2026-08-01):** Initial template. Five-field contract merged with OpenSpec front matter, model/escalation fields added per the router, wave and serial-lane dispatch mechanics, escalation-over-fan-out policy, HANDOFF receipt block, hardening checklist as Appendix A.
