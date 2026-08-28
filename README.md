# pulse

Patient unified ledger of state and events

## Quickstart

```bash
task install
task check
```

Run `task` on its own to list every command, grouped by area and in workflow order.

`task check` needs no Java. Java (17+) is a prerequisite of `task synthea:regen PROFILE=<p>`
only — the deterministic synthetic-population regeneration in `packages/synthea-seed`, which
shells out to the checksum-pinned Synthea JAR and verifies the output against the profile's
committed manifest. Manifests are authored from the CI runner's output (`REPIN=1`, an explicit
reviewed change); if a local run diverges, the manifest diff names the files and the CI
artifact from `synthea-regen.yml` is the receipt of record.

## Status

Latest program status: [`.planning/reports/2026-08-03-program-status.md`](.planning/reports/2026-08-03-program-status.md).

## How this repo is organised

- `AGENTS.md` — operating contract for agents working in Orca worktrees. Binding.
- `CLAUDE.md` — session contract for Claude Code, including PHI rules.
- `openspec/` — change lifecycle: proposal, design, specs, tasks, archive.
- `docs/contracts/` — what this repo publishes and consumes. Cross-repo integration goes
  through these, never by cloning another repo into this one.
- `docs/adr/` — architecture decisions, append-only.
- `tests/scaffold/` — gates that validate the repo's own structure and wiring.

## Template

Generated from [repo-ade](https://github.com/robford-brookai/repo-ade). Pull later template fixes with
`task template:diff` and `task template:sync`; both leave this file alone.
