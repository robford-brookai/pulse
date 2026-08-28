# Tasks — workflow-v2-1-efficiency

Annotation format per the dispatch template: `[model | deps | lane | wave]`, `serial:` carries
its own justification. Default model is `sonnet`, stated explicitly per
`model_declared_or_default`. WORKFLOW.md and Taskfile edits are serial-lane by standing rule
(workspace roots, generated-surface adjacency).

## 1. Workflow document (the meta-change proper)

- [x] 1.1 WORKFLOW.md v2.1.0: add the `replan` step to the YAML (reachable from `execute`, next:
      sync_linear), add its `state_resolution` rule ahead of the execute check, rewrite the three
      machine-local resolution rules per design D5, drop worktree existence from resolution,
      tighten `main_access` to name checkbox state as the only tasks.md content eligible for
      direct push, and update prose §3, diagram §4, and the change log in the same commit.
      Done when `task workflow:lint` passes and every new status/step string resolves.
      `[model: fable | deps: — | lane: repo_change | wave: 0]`
      `serial: openspec_main_specs` — the workflow document governs every other agent's behavior.
- [x] 1.2 `scripts/workflow.py`: extend the lint so the new step, edges, and resolution rules are
      schema-valid, and add a regression test that the v2.1.0 block parses and cross-references
      cleanly. Tests first.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 0]`

## 2. Checkoff automation

- [x] 2.1 `scripts/checkoff_tasks.py` + `task checkoff CHANGE=<id>`: parse
      `git log <last-checkoff>..main` subjects for the `(X.Y[, DNA-nnn])` convention, flip
      matching unchecked boxes only, refuse unknown ids nonzero, no-op cleanly when nothing
      merged, commit message lists source SHAs/PRs. Tests first: subject-parsing table test,
      unknown-id refusal, idempotent rerun, checkbox-only diff assertion.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
- [x] 2.2 Wire checkoff into the docs: dispatch-template §4 gains the automated path ("checking
      one off is the act that opens the next wave" now names `task checkoff` as the normal actor),
      WORKFLOW.md merge step behavior mentions it, `task -l` grouping ordered per convention.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 1]`

## 3. Linear id write-back

- [x] 3.1 `scripts/linear_sync.py`: on APPLY create success, insert the `[<TEAM>-<n>]` token into
      the task's line when absent — never rewrite an existing token, never touch any other
      content, dry run prints the pending write-back. Tests first: insertion, existing-token
      no-op, dry-run purity, failed-create writes nothing (mock the client — no live network in
      tests).
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      Model `opus`: the mutation-ordering edge cases (partial apply failure mid-run) need
      judgment; the verifier is the mocked-client test suite.

## 4. Tracked state

- [x] 4.1 `.gitignore`: narrow `handoffs/` so `handoffs/*/SUMMARY.md` tracks while per-task
      scratch stays ignored — mind directory-level negation semantics (ignore contents, not the
      directory). Add a scaffold gate asserting `git check-ignore` rejects the summary path and
      accepts a scratch path, and extend the cat9 golden workflow to commit the summary.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
      `serial: workspace_roots` — edits the root ignore file and scaffold gates.
- [x] 4.2 `scripts/collect_handoffs.py`: assert the summary it writes lands on a tracked path,
      and document the receipts-and-spec-deltas-only content rule (PHI review-reject) in the
      template HANDOFF and dispatch-template §5. Tests first.
      `[model: sonnet | deps: 4.1 | lane: repo_change | wave: 2]`

## 5. Verification and upstreaming

- [x] 5.1 Full pass: `task check`, `task verify CHANGE=workflow-v2-1-efficiency`, and a dry-run
      exercise of the new edges — `task checkoff` against this change's own merged PRs, a
      dry-run `linear:sync` showing a planned write-back, `workflow:lint` green.
      `[model: sonnet | deps: 2.2, 3.1, 4.2 | lane: repo_change | wave: 3]`
- [x] 5.2 Record the template-bound pieces (checkoff target, write-back, gitignore narrowing,
      lint extension) as a repo-ade issue per the fix-upstream rule — filed, not implemented
      here.
      `[model: sonnet | deps: 5.1 | lane: repo_change | wave: 3]`
      Filed: robford-brookai/repo-ade#6

## 6. Coordinator ergonomics (amendment — review-and-merge is the only human step)

- [x] 6.1 `scripts/checkoff_tasks.py`: accept repeatable `--commit <sha>` to record explicit
      merge commits, and print pre-filled follow-up commands (`task dispatch CHANGE=<id>`) after
      any flip. Taskfile passes `COMMIT_SHA`. Tests first.
      `[model: sonnet | deps: 2.1 | lane: repo_change | wave: 4]`
- [x] 6.2 `task replan CHANGE=<id>`: dispatch gains `--validate-only` (mechanical G_MECE checks,
      no hardening gate, no emission); the target runs it plus `openspec validate` and prints the
      pre-filled sync/dispatch follow-ups. WORKFLOW.md replan step names the target.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 4]`
- [ ] 6.3 CLAUDE.md gains standing orders for the coordinator (the agent on main): checkoff with
      the merged SHA after each PR merge, replan validation before opening amendment PRs, collect
      + commit SUMMARY.md at wave end — every command pre-filled with the active change id, which
      is the sole non-archive entry in `openspec/changes/`.
      `[model: sonnet | deps: 6.1, 6.2 | lane: repo_change | wave: 5]`
