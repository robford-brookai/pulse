TASK C: QUALITY ASSURANCE OF TASKS A AND B, AND THE BOOMERANG

Placeholders the coordinator fills before dispatch: {{DATE}}, {{HEAD_SHA}}, {{PRIOR_SCORECARD}}
(path of the previous devex-scorecard report), {{SCRATCH_DIR}}.

CONTEXT
- Repo: /Users/Rob.Ford/Repos/robford-brookai/pulse at {{HEAD_SHA}} on main. READ-ONLY except
  your own report. No PHI. No production network. Do not commit.
- Contract both tasks were to follow: docs/process/devex-audit/task-a.md, task-b.md, rubric.md.
- You are the only agent allowed to read the prior scorecard and the inner-tier files
  (tests/scaffold/cat10_devex.py, scripts/devex/, .planning/devex/). Use them for the boomerang
  and for the "moved without a PR" check, not to score.
- Writing: plain, no em-dashes, no emojis.

INPUT
- Task A: .planning/reports/{{DATE}}-devex-audit-evidence.md
- Task B: .planning/reports/{{DATE}}-devex-scorecard.md
- Prior scorecard: {{PRIOR_SCORECARD}}

YOUR JOB: make sure the other two did their job. Be adversarial.
1. Coverage: checklist from Steps 0-8 and the Task A spec (fresh clone timed, 6+ errors quoted
   verbatim, connector scaffold attempt, eight persona questions answered in Step 4, gap-method
   entries, journey table with INFERRED rows marked, top-10, method notes). PASS/PARTIAL/FAIL
   with line references.
2. Evidence integrity: re-run at least 15 of Task A's cited commands, including a second
   independent fresh clone into {{SCRATCH_DIR}}/qa-fresh with its own TTHW timing, at least 3
   triggered errors, and `mkdocs build -s`. Confirm quoted output and timings within reason. Open
   every cited file path; list any that do not exist or do not say what is claimed.
3. Score calibration: for each of Task B's scores check (a) verifiable evidence cited, (b)
   consistent with the rubric wording and TTHW table, (c) 10 means best practice, not defect-free,
   (d) composite weights are the fixed ones and the arithmetic is right, (e) overall is the
   unweighted mean. Flag any score you would move by 2 or more points and say why.
4. Boomerang: table of prior vs current score per dimension, characteristic and composite, with
   delta. For every dimension that rose 3 or more points, name the merged PR(s) on main since the
   prior audit that account for it (`git log --oneline <prior_sha>..HEAD`). A rise with no PR
   behind it is a finding against Task B.
5. Scope: connectors weighted heaviest in both reports, whole repo still covered.
6. Hygiene: no PHI; no tracked file modified by A or B (`git status --porcelain`; only the two
   new reports should be new); no commits; no em-dashes or emojis in the reports; `CHECKSUMS`
   verifies (`uv run python scripts/devex/check.py --verify-only`).

OUTPUT
Write .planning/reports/{{DATE}}-devex-audit-qa.md with: a verdict per task (ACCEPT / ACCEPT WITH
CORRECTIONS / REJECT), the coverage checklist, the evidence re-run table (command, claimed,
observed, match), the score calibration table, the boomerang table, required corrections ordered
by severity, and a "trust statement" saying which numbers a reader can rely on as-is. Do not edit
the other two reports.

When finished, send exactly one worker_done with the injected ids, --outcome succeeded or
failed, --files-modified set to your report path, and the two verdicts first in the body.
