TASK B: SCORE THE AUDIT (0-10 per dimension, 10 = closest to best practice)

Placeholders the coordinator fills before dispatch: {{DATE}}, {{HEAD_SHA}}.

CONTEXT
- Repo: /Users/Rob.Ford/Repos/robford-brookai/pulse at {{HEAD_SHA}} on main. READ-ONLY except
  your own report. No PHI. No production network. Do not commit.
- Rubric: docs/process/devex-audit/rubric.md, applied as written including the internal-repo
  interpretation. 10 means the best-practice bar the rubric describes, adapted to an internal
  platform repo; it does not mean "no visible defects", which is a 7 to 8.
- Blindness: do NOT read any prior scorecard or QA report, nor the per-run check output
  (.planning/devex/*-check.json). You score this audit's evidence only; the boomerang comparison
  is Task C's job. For dimension 8 (DX measurement) you MAY open tests/scaffold/cat10_devex.py,
  scripts/devex/, and .planning/devex/loop.jsonl to verify Task A's claims about the repo's own
  measurement; do not read the prior audit's scores inside the ledger rows.
- Writing: plain, no em-dashes, no emojis.

INPUT
Task A's evidence: /Users/Rob.Ford/Repos/robford-brookai/pulse/.planning/reports/{{DATE}}-devex-audit-evidence.md.
Read it fully first.

YOUR JOB
1. Score the 8 audit dimensions (Getting Started, API/CLI/SDK Ergonomics, Error Messages,
   Documentation, Upgrade Path, Developer Environment, Community & Ecosystem, DX Measurement)
   and the Seven DX Characteristics on the rubric's 0-10 scale. Anchor Getting Started with the
   TTHW table (Champion under 120s, Competitive 120-300s). State confidence per score.
2. Before scoring a dimension, spot-check at least two pieces of Task A's evidence for it by
   opening the cited files or re-running the cited command. Mark unverifiable evidence and score
   only on what you verified, at low confidence.
3. Connector weighting: produce a "Connector author DX" composite as the headline. Use these
   fixed slices and weights so audits are comparable: Kit API ergonomics 30, Connector
   documentation 20, Getting started to a working connector 15, Errors on the connector path 15,
   Dev environment for a new package 10, Kit upgrade path 5, Ecosystem and support 3,
   Measurement of author experience 2. Show the arithmetic.
4. Overall DX = unweighted mean of the eight dimensions, one decimal.
5. Gap method: for every score below 9, state what a 10 looks like for this repo and the single
   highest-leverage change toward it. Each "10" must exceed "defect-free".
6. Rank the top 10 fixes by adoption impact over effort (S under an hour, M a session, L
   multiple sessions), each tied to a DX First Principle by number. Then list "below the cut".

OUTPUT
Write /Users/Rob.Ford/Repos/robford-brookai/pulse/.planning/reports/{{DATE}}-devex-scorecard.md
with: header (date, HEAD, inputs, rubric path), headline (connector composite and overall),
scorecard table (dimension, score, confidence, method, evidence pointer), Seven Characteristics
table, composite table with arithmetic, gap-method entries, ranked fixes, and an "Evidence
disputes" section listing anything in Task A's report you could not verify or disagree with. Do
not edit Task A's file.

When finished, send exactly one worker_done with the injected task and dispatch ids,
--outcome succeeded or failed, --files-modified set to your report path, and the two headline
numbers in the subject.
