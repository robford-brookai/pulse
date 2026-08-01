# Workflow

Order of operations for the ADE stack: OpenSpec (planning), OpenLore (drift and memory), Orca
(execution), Taskfile, and the thin-glue scripts.

Run `task` for the command list, grouped by area in the order below.

---

## 1. What generation already did

`bootstrap.sh` ran during generation, so this repo is already initialised. It renamed the
package, wrote `.openlore/config.json` (`openlore init`), built the call graph
(`openlore analyze`), installed dependencies and pre-commit hooks, committed, and pushed. CI was
watched to green before the script exited.

Confirm the inherited state before starting work:

```bash
task install     # no-op if bootstrap already synced
task check       # lint, typecheck, tests, docs build — exactly what CI runs
```

Do **not** run `openlore drift --install-hook`. Drift is already wired through the
`openlore-drift` entry in `.pre-commit-config.yaml`; that flag writes `.git/hooks/pre-commit`
directly and takes the file over from the pre-commit framework.

---

## 2. `openspec/specs/` starts empty, and that is correct

A fresh repo has `openspec/specs/` holding only a `.gitkeep` — git cannot carry an empty
directory through a template clone. Nothing is wrong and nothing is blocked:

```bash
task lore:drift        # [ok] No changes detected. Specs are up to date.
```

Drift passes against an empty specs directory. (A *missing* one is a hard failure, which is why
the `.gitkeep` is tracked — but that is the template's problem, already solved.)

`openlore analyze` will note *"Spec index skipped … contains no spec.md files — run 'openlore
generate'"*. Ignore it here. That is openlore suggesting the brownfield path, and this repo has
no code to derive specs from yet — `src/` is a placeholder.

**Specs arrive when your first change is archived.** `/opsx:propose` writes delta specs under
`openspec/changes/<name>/specs/`, and `task spec:archive` merges them into `openspec/specs/`,
which then becomes the baseline the next change starts from. Sections 3 and 7. Specs describe
the intent you planned, never an inference drawn from placeholder code.

Useful once real code exists:

```bash
task lore:analyze      # rebuild the call graph after a significant refactor
```

### Adopting an existing codebase

Different situation, off the default path: you are pointing this scaffold at a project that
already has substantial code and no specs. Then deriving a baseline is the point.

```bash
openlore generate      # derive living specs from the analysis (needs an LLM provider key)
```

Do not run this on a freshly generated repo. It would describe the scaffold's own placeholder
and gate suite, write that into `openspec/specs/`, and hand it to every future agent through
`orient()` as though it were your design.

---

## 3. Plan a change

Each feature, fix, or refactor is one OpenSpec change.

```bash
/opsx:propose "Add JWT authentication"
```

That writes `openspec/changes/add-jwt-auth/` containing `proposal.md`, `design.md`,
`specs/<capability>/spec.md`, and `tasks.md`. Edit them until they describe the change
accurately — this is the artifact every downstream agent reads.

```bash
task spec:validate CHANGE=add-jwt-auth
```

Then check the plan by hand. Validation catches format, not sense:

- every requirement has at least one Given/When/Then scenario
- tasks are atomic — one commit each, roughly two hours or less
- every task maps to at least one scenario
- no two tasks overlap (mutually exclusive)
- every scenario is covered by some task (collectively exhaustive)
- blocking dependencies are stated in the task description

If any of these fails, revise and re-validate. Do not dispatch a plan that has not passed.

---

## 4. Parse the plan into work orders

```bash
task dispatch CHANGE=add-jwt-auth
```

`scripts/dispatch_tasks.py` parses `tasks.md` and writes one self-contained work order per task
to `work_orders/add-jwt-auth/task-001.md`, `task-002.md`, and so on. Each carries the objective,
the milestone, a pointer to the change's specs, and the HANDOFF.md requirement.

Targets take go-task **variable** syntax. Passing the change as a `--change <name>` flag instead
exits 2 with `unknown flag`.

The command prints a ready Orca invocation per work order:

```bash
orca worktree create --name task-001 --repo path:$PWD \
  --agent claude --prompt "$(cat work_orders/add-jwt-auth/task-001.md)" --setup run --json
```

Requires `orca serve` or the Orca app running. Work orders are independent by construction, so
run as many worktrees concurrently as the plan allows.

Each agent then follows `AGENTS.md`: read the contract, call `orient()` via the OpenLore MCP
server, read the spec and its task, write the failing test first, implement, run `task check`,
write `HANDOFF.md`, and make exactly one commit.

---

## 5. Collect handoffs

```bash
task collect CHANGE=add-jwt-auth
```

Gathers every worktree's `HANDOFF.md` into `handoffs/add-jwt-auth/` and writes a `SUMMARY.md`
for the doc-updater. Worktrees without a handoff are skipped — that is a valid outcome, meaning
the agent had nothing spec-relevant to report.

---

## 6. Apply spec updates

Implementation agents never edit specs. A fresh session does, reading only the handoffs:

```note
Read handoffs/add-jwt-auth/SUMMARY.md and each handoff it references. Apply ONLY
plan-relevant updates to openspec/changes/add-jwt-auth/specs/. Ignore implementation
details. If a handoff contains "## Design Drift", flag it for human review and do not
apply it. Run `openspec validate add-jwt-auth` when done.
```

`task sync-docs CHANGE=add-jwt-auth` runs the drift and validation checks around that step and
prints the same reminder.

---

## 7. Verify, merge, archive

```bash
task verify CHANGE=add-jwt-auth   # check + drift + spec validation
```

Merge through Orca's diff review — compare worktree diffs, annotate, take the winning changes,
delete spent worktrees. Then:

```bash
task spec:archive CHANGE=add-jwt-auth
```

Archive is gated on `spec:validate`, `lore:drift`, and `test`, so it refuses to run on a change
that is not clean. It merges the delta specs into `openspec/specs/`, which becomes the baseline
the next change starts from — and which `orient()` will surface to the next round of agents.

---

## 8. Keep the scaffold current

This repo was generated from a template that keeps changing:

```bash
task template:diff    # what changed upstream since generation
task template:sync    # apply it to infrastructure paths only
```

`template:sync` rewrites the template's package name to this repo's before applying, and never
touches `README.md`, `CLAUDE.md`, `AGENTS.md`, `pyproject.toml`, `src/`, `docs/` or `openspec/`.
Run `task check` afterwards.

---

## The loop

```mermaid
GENERATED (bootstrap already ran: init, analyze, sync, hooks, commit, CI green)
    │                                    openspec/specs/ is empty — expected
    ▼
PER CHANGE
  propose → validate → MECE check → dispatch → Orca worktrees → collect
     ▲                                                             │
     │                        doc-updater ←───────────────────────┘  (handoffs only)
     │                              │
     │                      verify → merge → archive
     │                                          │
     └──────────────────────────────────────────┘
        archive merges the change's delta specs into openspec/specs/,
        which becomes the baseline the next change starts from
```

---

## Decision points

| If… | Then |
| --- | --- |
| The plan fails the MECE check | Revise specs and tasks, re-validate. Do not dispatch. |
| An agent hits a spec contradiction | It writes `## Design Drift` to HANDOFF.md and stops. A human resolves the spec before re-dispatching. |
| A worktree produced no HANDOFF.md | Fine if nothing spec-relevant changed. If behaviour changed undocumented, write the handoff yourself from the diff. |
| `openlore drift` reports drift | Check the handoffs cover it. If not, update specs manually. Do not archive with unresolved drift. |
| A task landed without tests | Do not merge. Send the agent back — tests first, then implementation. |
| `task check` passes but CI fails | The workflow ran something `check` does not. Add it to `check`; local and CI must not drift. |
| `openlore analyze` says the spec index was skipped | Expected until your first change is archived. Only act on it when adopting an existing codebase — section 2. |
