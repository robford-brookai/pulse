# Handoff Summary: connector-pattern

Collected 2 handoff(s).

## Files

- task-009.md, task-010.md were never committable (`.gitignore:236` ignores everything
  under `handoffs/` except `SUMMARY.md`) — their content is superseded by the 2.5 receipt
  below.

## 2.5 receipt — Wave-1 regression, demos 1-4

Commit run against: `992a78795da3e16f9fdeef9b7a1bdc790805eb63` (origin/main).

**Demo 1 — offline** (`task demo:1`, LocalStack + Postgres via
`packages/ocean/infra/docker-compose.yml`): stack came up healthy; 4/4 assertions passed
(legal command commits; illegal command rejects with catalog reason + version; replay
returns the original event id; independent fold equals `current_state`); exit `0`. Stack
torn down after the run.

**Demo 2 — offline** (`task demo:2`): `demo2_identity_matcher.py` 4/4 assertions passed
(exact-identifier short-circuit; composite mint, zero candidates; two-candidate
quarantine; identifier-conflict split); `demo2_kanban_drag.py` 3/3 assertions passed
(legal signed drag commits; invalid drag rejects with a receipt/comment; tampered
signature rejected as unauthenticated); exit `0`. No PHI, synthetic keys only.

**Demos 3 and 4 — covered by the Demo 5 live run, not re-run.** Per the 2026-09-08
owner decision, the attended live run on 2026-09-02 recorded on issue #342 (third
comment, image `1c7f383`, all six stages passed across two runs, including the signed
kanban drag and the verdict declare-back on dev) stands in for demos 3 and 4, which
exercise the same seams. No separate attended session was run.

Full receipt posted as a comment on issue #319:
https://github.com/robford-brookai/pulse/issues/319#issuecomment-5593576925

## Doc-Updater Instructions

1. Read each handoff file above.
2. For each spec-relevant update, edit the corresponding file in:
   `openspec/changes/connector-pattern/specs/`
3. Run `openspec validate connector-pattern` to check format.
4. Run `openlore drift` to check for new drift.
5. Ignore implementation details — only apply plan-relevant changes.
6. If a handoff contains `## Design Drift`, flag for human review.
