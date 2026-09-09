# Design: devex-eight

## Context

Baseline audit 2026-09-02 at `99d9b7a`: overall 3.8, connector 2.4. All defects still present at
`3da0baf`. The audit method was three agents (evidence, scoring, QA) run once by hand under Orca
orchestration; nothing preserved it. `/autoresearch` exists but needs a blocking script printing
one fast number and auto-commits keeps, so it cannot drive a 35-minute LLM audit.

## Goals / Non-Goals

**Goals**
- A Karpathy loop whose inner metric is cheap, deterministic and hard to game, and whose outer
  metric is the real audit, frozen so it cannot drift with the fixes.
- Reach the exit gate: overall >= 8.0 and connector >= 8.0 on a QA-accepted scorecard.
- Every fix ships with the test that flips its finding closed.

**Non-Goals**
- No 0-10 proxy. No rubric edits inside this change. No pre-planned waves beyond 2.

## Decisions

1. **The inner metric is a count, not a score.** `devex_open_findings` = number of `xfail` tests
   in `cat10_devex.py`. A hand-weighted 0-10 built from the fixes already planned would read 8.0
   the moment the checklist is green; that is Goodhart's law with extra steps. A count that
   ratchets to zero, with `strict=True` so a fixed finding must have its marker removed and a
   regressed one fails `task check`, is honest and monotone.
2. **Protocol frozen by checksum, enforced in `task check`.** `docs/process/devex-audit/{README,
   rubric,task-a,task-b,task-c}.md` are hashed into `CHECKSUMS`; `cat10` and `check.py` verify.
   A protocol change is its own PR and regenerates the file with `--freeze`. So the measurement
   cannot move with the thing measured.
3. **Blindness by spec.** A reads the newcomer's path only; B scores A's evidence and its own
   spot checks; only C reads the prior scorecard and the inner-tier files, does the boomerang,
   and flags any dimension that rose 3+ points without a merged PR. Persona connector rotates.
4. **Outer tier runs only at `open_findings == 0`.** Running it earlier re-reports what the
   inner tier already knows. Its top-10 seeds a new change, per WORKFLOW's replan gate, rather
   than growing this tasks.md.
5. **Keep/discard at PR granularity.** Merge requires `task check` green and the count not
   rising. The ledger row per merge is the experiment log.
6. **Template-owned paths fixed locally first.** pulse's `Taskfile.yml` has 63 targets and is
   2,981 lines behind the template; blocking a one-line fix on a sync is the wrong trade. One
   batched repo-ade PR follows wave 2. `ci-health.yml` and `auto-heal.yml` do not exist upstream.
7. **`python_files` widened to `cat[0-9]*_*.py`.** The old pattern silently skips a two-digit
   gate; `cat10` includes a self-check that its own filename is collected.
8. **Task C owns the boomerang.** B must stay blind to the prior score to avoid anchoring.

## API surface

- `task devex:check` -> stdout `METRIC devex_open_findings=<n>`, file `.planning/devex/<date>-check.json`
  `{date, head, open_findings, regressions, fixed_but_still_marked, protocol_frozen, results}`.
  Exit 1 on regression or broken checksum.
- `task devex:audit` -> prints the runbook and today's three report paths.
- `scripts/devex/check.py --freeze | --verify-only | --prep-audit`.
- `.planning/devex/loop.jsonl` rows: `{date, kind: pr|audit, ref, open_findings, overall?, connector?, qa?}`.

## Risks

- Audit variance between runs. Mitigation: fixed weights and slices in task-b, C re-measures and
  boomerangs, exit gate needs QA acceptance.
- Internal-repo interpretation of Community read as grade inflation. Mitigation: stated in the
  frozen rubric before any scoring, and C is told to flag it if B stretches it.
- Serial-lane contention with `billing-connector` on `Taskfile.yml`. Mitigation: dispatch holds
  serial tasks; the coordinator releases one at a time.
