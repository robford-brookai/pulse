---
name: "DevEx audit"
description: "Run the repeatable three-agent developer-experience audit (evidence, scoring, QA) via Orca orchestration, or the deterministic findings check"
allowed-tools: Bash(task:*), Bash(orca:*), Bash(uv:*), Bash(git:*)
category: "Workflow"
tags: ["devex", "audit", "orchestration", "measurement"]
---

Run the DevEx audit. The runbook is `docs/process/devex-audit/README.md`; read it first and
follow it exactly. It is frozen by `docs/process/devex-audit/CHECKSUMS`; never edit it or the
`task-*.md` specs inside a `devex-*` change.

**Input**: the argument after `/devex-audit`:
- nothing or `check`: run `task devex:check` and report `devex_open_findings` and any REGRESSION lines.
- `full`: the outer tier. Run `task devex:audit` for today's report paths, then coordinate the
  three agents (A evidence, B scoring, C QA) with Orca orchestration as the runbook describes.
  Do not substitute non-Orca subagents. Do not start the outer tier while `devex_open_findings`
  is above 0 unless the user says so.

**On completion of `full`**: append the ledger row to `.planning/devex/loop.jsonl`, apply C's
required corrections to A's and B's reports, and open a PR with the three reports and the ledger.
Report the two headline numbers and C's verdicts, then whether the exit gate (overall >= 8.0 and
connector >= 8.0, QA-accepted) holds.
