# Design — workflow-v2-1-efficiency

## Context

See proposal.md — Why. The relevant machinery today: `scripts/dispatch_tasks.py` reads tasks.md
checkboxes to release waves, `scripts/linear_sync.py` is dry-run-by-default and strictly
file → Linear, `scripts/workflow.py` lints the WORKFLOW.md YAML against its projections, and
`.gitignore` excludes `work_orders/`, `handoffs/`, and `.orca` wholesale. This is a meta-change
per WORKFLOW.md's `edit_protocol`: the YAML edit ships through its own OpenSpec change with the
prose and diagram updated in the same commit, and `task workflow:lint` is the correspondence
gate. Constraint carried from CLAUDE.md: the scaffold gates and golden tests must stay green, and
anything template-shaped gets fixed upstream in repo-ade after landing here.

## Goals / Non-Goals

**Goals:**
- Zero hand-typed bookkeeping commits per task after this lands
- Every real event observed in the ocean run has a legal graph edge
- `state_resolution` answers identically on any clone
- The tier-economics receipts the escalation ladder is priced against actually accumulate in git

**Non-Goals:**
- No GitHub webhook, bot, or CI-side automation — checkoff is a local target the operator (or an
  agent at merge) runs, same trust model as every other task target
- No two-way Linear sync beyond the id token — content direction of truth is untouched
- No change to wave semantics, G_MECE content, the escalation ladder, or lanes
- Not tracking `work_orders/` or per-task HANDOFF files — they are regenerable and worktree-local

## Decisions

**D1 — Checkoff parses main's history, not the GitHub API.** The task id convention
`(X.Y[, DNA-nnn])` already appears in merge subjects, so `git log <last-checkoff>..main` plus a
regex is enough, works offline, and needs no credentials — consistent with "CI has no secrets by
default." Alternative considered: `gh pr list --state merged`, rejected because it adds an auth
dependency for information git already holds. The subject convention becomes normative: dispatch
already writes the id into the work-order title, so the PR title inherits it for free.

**D2 — Checkoff is a distinct target, invoked explicitly, committing directly.** Alternatives:
(a) flip the checkbox inside each task's own PR — rejected, it makes every parallel worktree
touch tasks.md, manufacturing the serial-lane conflict the workflow exists to avoid; (b) a
post-merge git hook — rejected, hooks are per-clone and invisible, and a silent auto-commit to
main is exactly the class of magic `main_access` was written to bound. Explicit
`task checkoff CHANGE=<id>` after a merge session keeps the act visible while collapsing 25
commits' worth of typing into one command, and it may batch — one commit recording several
merges is already the observed pattern.

**D3 — `replan` is a step, not a gate.** It reuses G_MECE rather than growing a fifth gate: the
delta-scoped check is the same assertions run over the amended lines. `state_resolution` places
the new rule between the work-order staleness check and the execute check, so an amended-but-
unsynced tasks.md resolves forward through sync/dispatch rather than parking at execute.
Alternative considered: routing amendments through the full validate step — rejected, full
revalidation of a 56-task file to add two tasks is the friction that produced the direct pushes.

**D4 — Write-back inserts the id token by line match, idempotently.** `linear_sync.py` already
parses task lines to build its operation plan, so it knows the exact line for each create; the
write is an insertion of `[<TEAM>-<n>]` after the task number, only when no id token is present,
only on APPLY runs, applied after the Linear mutation succeeds so a failed create never writes a
phantom id. The file write is a plain edit the operator commits with the sync (mechanical,
main_access-eligible). Alternative considered: a sidecar id-map file — rejected, tasks.md is
where every human and dispatch already reads ids, and a second file is a second drift surface.

**D5 — Narrow the gitignore instead of relocating handoffs.** `.gitignore` changes from
`handoffs/` to ignoring `handoffs/**` while negating `handoffs/*/SUMMARY.md` (exact patterns to
be settled against gitignore negation semantics — a directory-level ignore blocks negation of
its children, so the rule pair must ignore contents, not the directory). This keeps every path
in WORKFLOW.md and the glue scripts unchanged. The three state_resolution rules rewrite to:
work-order staleness → "tasks.md has unchecked tasks whose deps are all checked and no open PR
references them" is *not* attempted — instead the rule simply drops the staleness clause and
keys on tasks.md annotations vs sync receipts; SUMMARY.md absence now reads the tracked file;
worktree existence moves out of resolution entirely and becomes an H7 hygiene report at merge.

**D6 — Version bump to 2.1.0, one changelog entry.** Steps are added, none repurposed, honoring
`edit_protocol`'s stable-id rule. The dispatch template gets a §4 note (automated checkoff path)
and a §5 note (SUMMARY.md is tracked); both are doc edits riding this change.

## Risks / Trade-offs

- [Checkoff regex matches a task id in an unrelated commit subject] → The pattern anchors on the
  `(X.Y` / `(X.Y,` convention at end-of-subject and checkoff refuses ids not present in tasks.md;
  a false positive still only flips a box whose PR reviewer will see the flip in the checkoff
  commit message listing its source SHAs.
- [Gitignore negation silently fails and SUMMARY.md stays untracked] → cat1 gates assert
  `git check-ignore handoffs/x/SUMMARY.md` fails and scratch paths (shallow and nested) pass;
  cat9's fresh-clone smoke runs those same gates in a clone, so the class is covered without a
  separate golden extension.
- [Write-back races a hand edit to tasks.md] → sync already treats the file as canonical input;
  the write-back happens on the operator's working copy in the same session, and an id token
  collision (line already has one) is a no-op by rule.
- [Replan becomes a loophole for scope creep] → the edge requires a PR and delta-G_MECE; the
  main_access text tightens in the same commit to name checkbox state as the only tasks.md
  content eligible for direct push.
- [Tracked SUMMARY.md could carry sensitive operational detail] → collect already restricts
  content to receipts and spec deltas; the PHI rule in the spec makes it a review-reject, and
  out-of-lane (CCC) work never enters collect anyway.

## Migration Plan

Land as ordinary PRs in dependency order (WORKFLOW.md + lint first, then glue scripts, then
gitignore/gates, then template notes). No state migration: the current change's tasks.md already
satisfies the conventions. Rollback is `git revert` per PR — write-back ids already in tasks.md
are inert, and a reverted gitignore merely stops tracking future summaries.

## Open Questions

- Whether repo-ade upstreams D1's subject convention as a lint on PR titles or leaves it
  documented-only — deferred to the template sync, does not change this repo's behavior.
