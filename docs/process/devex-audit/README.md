# DevEx audit runbook

The repeatable measurement behind the `devex-*` changes. Say `/devex-audit` in a Claude Code
session on `main`, or run `task devex:audit`, and follow this page. Two tiers:

| Tier | Command | Cost | Output |
|---|---|---|---|
| Inner, deterministic | `task devex:check` | seconds | `METRIC devex_open_findings=<n>` and `.planning/devex/<date>-check.json` |
| Outer, LLM-judged | `/devex-audit` | about 35 minutes, three Opus agents | three reports under `.planning/reports/` and a ledger row |

The inner tier is a regression gate, not a score. It counts audit findings that are still open
(`tests/scaffold/cat10_devex.py`, one test per finding, `xfail(strict=True)` while the defect
exists). It never prints a 0-10. The only 0-10 comes from the outer tier.

## Exit gate

Overall DX >= 8.0 and connector-author composite >= 8.0, on a scorecard the QA agent accepted,
from a run of the protocol below with the frozen specs in this directory unchanged
(`CHECKSUMS` verified by `task devex:check`).

## When to run the outer tier

Run `task devex:check`. When `devex_open_findings` is 0, run `/devex-audit`. The new scorecard's
top-10 seeds the next `devex-*` change. Repeat until the exit gate holds. Do not run the outer
tier while findings are open; it will re-report what the inner tier already knows.

## Protocol

Three agents, one Orca Run, tasks chained A -> B -> C. Specs are the files beside this page:
`task-a.md` (evidence), `task-b.md` (scoring), `task-c.md` (QA). Each spec is complete on its
own; the coordinator fills in the four placeholders listed in each file's header.

Blindness rules, enforced by the specs:

- A collects evidence from the persona's path only. It does not read any prior audit report or the
  per-run check output. In Step 8 it may read the repo's own measurement machinery
  (`tests/scaffold/cat10_devex.py`, `scripts/devex/`, `.planning/devex/loop.jsonl`), since that
  machinery is what Step 8 audits (protocol change 2026-09-04, after QA 6.1 of the second audit).
- B scores from A's evidence and its own spot checks. It does not read the prior scorecard or the
  check output; for dimension 8 it may verify A's claims against the same measurement files.
- C does the boomerang: compares B's scorecard to the prior one, re-runs at least 15 cited
  commands on a second fresh clone, re-measures TTHW, and flags any dimension that rose 3 or
  more points without a merged PR behind it.
- The persona's target connector rotates each audit and is never `billing`.

## Coordinator steps

1. Prepare: `task devex:audit` prints this page and the three report paths for today.
2. Create the Run and tasks:

   ```bash
   orca orchestration run-create --objective "devex audit <date>" --json
   orca orchestration task-create --spec "$(cat docs/process/devex-audit/task-a.md)" --json
   orca orchestration task-create --spec "$(cat docs/process/devex-audit/task-b.md)" --deps '["<task_a>"]' --json
   orca orchestration task-create --spec "$(cat docs/process/devex-audit/task-c.md)" --deps '["<task_b>"]' --json
   ```

   Replace the placeholders in each spec first (date, prior scorecard path, persona connector,
   HEAD sha). `sed` on a copy in the scratchpad is fine; never edit the frozen files.
3. Start each worker on a Claude terminal launched with auto permissions, then bind it:

   ```bash
   orca terminal create --worktree path:<repo> --title "DEVEX-A" --command "claude --permission-mode auto --model opus" --json
   orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 90000 --json
   orca orchestration worker-start --task <task_a> --run <run> --worktree current --terminal <handle> --json
   ```

   Workers launched with the default permission mode stall on shell prompts nobody answers.
4. Wait on the inbox for `worker_done`, then acknowledge by the `deliveryId` the consuming
   `check --wait` returns (not the message id), release the dispatch, close the terminal:

   ```bash
   orca orchestration check --run <run> --wait --types worker_done,escalation,question --timeout-ms 590000 --json
   orca orchestration check --run <run> --ack <deliveryId> --json
   orca orchestration worker-release --dispatch <dispatch> --json
   orca terminal close --terminal <handle> --json
   ```

   The wait streams `_keepalive` lines before the final JSON; filter them before parsing.
5. Start B when A's task is `completed`; start C when B's is. Send each a follow-up if the
   working copy is not on `main` at the audited HEAD (another session may have a branch out).
6. When C reports, append a ledger row to `.planning/devex/loop.jsonl`:

   ```json
   {"date": "<date>", "kind": "audit", "ref": "<head sha>", "open_findings": 0, "overall": <x.x>, "connector": <x.x>, "qa": "accept|accept-with-corrections|reject"}
   ```

7. Apply C's required corrections to A's and B's reports before anyone reads them. Commit the
   three reports and the ledger row on a branch; PR.

## Baseline

2026-09-02, HEAD `99d9b7a`: overall 3.8, connector 2.4, QA accepted with corrections. Reports:
`.planning/reports/2026-09-02-devex-audit-evidence.md`, `-scorecard.md`, `-qa.md`.

## Changing the protocol

`rubric.md`, `task-a.md`, `task-b.md`, `task-c.md` and this file are covered by `CHECKSUMS`.
A change to any of them is its own PR titled "devex-audit protocol: ..." and regenerates
`CHECKSUMS` with `uv run python scripts/devex/check.py --freeze`. It is never part of a
`devex-*` change, so the measurement cannot move with the thing measured.
