TASK A: RUN THE DEVEX AUDIT (evidence collection, NO scoring)

Placeholders the coordinator fills before dispatch: {{DATE}}, {{HEAD_SHA}}, {{PERSONA_CONNECTOR}}
(a system that is not billing, for example pocar or pap), {{SCRATCH_DIR}}.

CONTEXT
- Repo under audit: /Users/Rob.Ford/Repos/robford-brookai/pulse at {{HEAD_SHA}} on main. Work in
  place; do not create branches.
- Methodology: the frozen rubric at docs/process/devex-audit/rubric.md (DX First Principles,
  Seven DX Characteristics, Cognitive Patterns, Scoring Rubric, TTHW Benchmarks) and the eight
  audit steps below. The rubric includes the internal-repo interpretation; apply it as written.
- Persona: a competent engineer joining the team whose first job is to build a NEW connector for
  {{PERSONA_CONNECTOR}}. Walk their path: discover, clone, bootstrap, understand the connector
  kit, scaffold a connector, run tests, read errors, ship via the ADE workflow.
- Blindness: do NOT read any prior file matching .planning/reports/*devex*, nor the per-run check
  output (.planning/devex/*-check.json). You are measuring what a newcomer meets, not checking a
  list. The repo's own DX measurement machinery is part of what you audit in Step 8, so you MAY read
  tests/scaffold/cat10_devex.py, scripts/devex/, and .planning/devex/loop.jsonl there, as a newcomer
  who found them would; do not use them to steer Steps 0-7.
- Constraints: READ-ONLY on the repo except your own report file. No PHI anywhere. No live
  network calls to production systems. You MAY run local commands (task, uv, pytest, bash, git)
  and MUST clone the repo into {{SCRATCH_DIR}} to time a fresh onboarding. Do not modify any
  tracked file. Do not commit.
- Writing: plain, evidence-first, no em-dashes, no emojis. Every claim cites a file path, a
  command you ran plus its output, or a timing you measured. Tag each observation TESTED (you
  ran it), PARTIAL (ran part), or INFERRED (reasoned, not run).

YOUR JOB
Execute Steps 0 through 8 in the persona. Collect evidence, not scores. Do not assign numbers.

0. Target discovery: inventory the developer-facing surfaces (docs, task targets, packages,
   templates, scaffolding). State that the boomerang comparison is Task C's job, not yours.
1. Getting started: real fresh clone into {{SCRATCH_DIR}}, then the documented quickstart, timed
   to the second per stage. TTHW = clone to a green `task check` or the closest equivalent.
   Record every point where you had to read a doc, guess, or hit an error. Note cache warmth.
2. API/CLI/SDK ergonomics, connector-focused: attempt to understand and scaffold a connector for
   {{PERSONA_CONNECTOR}} following only what the repo tells you. Count files and docs read,
   concepts learned, whether a scaffold command exists, how far you got before getting stuck.
   Evaluate `task` help text and target naming. Compare the connector kit's public surface with
   the connector spec and with the reference connector's imports.
3. Error messages: deliberately trigger at least 6 realistic mistakes (wrong task args, missing
   env, missing tool, bad connector config, failing gate, gate in wrong dir). Quote exact error
   text. For each: does it state problem, cause and fix?
4. Documentation: findability, currency (stale references, `mkdocs build -s` warnings), whether
   the connector docs answer the persona's questions in this order: what is a connector here,
   what do I import, how do I scaffold, how do I configure, how do I test offline, how do I
   register the package, how do I ship through the workflow, who do I ask.
5. Upgrade path: template sync, .ade-template-version, ADR discipline, spec archiving, how a
   connector author absorbs a kit change.
6. Developer environment: toolchain requirements and pins, editor support, pre-commit hooks
   present after the documented install, local vs CI parity.
7. Community and ecosystem, internal-repo interpretation: CONTRIBUTING, owners, channels,
   templates, handoffs, work orders, Linear linkage.
8. DX measurement: does the repo measure its own DX (onboarding time, gate durations, drift)?

OUTPUT
Write /Users/Rob.Ford/Repos/robford-brookai/pulse/.planning/reports/{{DATE}}-devex-audit-evidence.md
with one section per Step (0-8): what you did (commands), what you observed (quoted output,
timings, file refs, TESTED/PARTIAL/INFERRED tags), friction points, and what a 10/10 would look
like for THIS repo, still without a numeric score. End with a "Connector author journey" table
(elapsed time, action, outcome, stuck points; mark any row you did not perform INFERRED) and a
"Top 10 friction points" list ordered by impact on connector authors, then "Method notes and
limits".

When finished, send exactly one worker_done using the task id and dispatch id Orca injected,
--outcome succeeded (or failed), --files-modified set to your report path, body summarizing the
top findings.
