## Why

The 2026-09-02 developer-experience audit (`.planning/reports/2026-09-02-devex-scorecard.md`,
QA-accepted in `2026-09-02-devex-audit-qa.md`) scored pulse at overall DX 3.8/10 and
connector-author composite 2.4/10. A new engineer reaches a green `task check` in about two
minutes and cannot build a connector at all: no authoring guide, no scaffold, a connector kit
whose `__all__` raises on import, a spec in two drifted copies describing an architecture the kit
does not implement, and three of eight package registrations that fail silently open. Rob's bar,
set 2026-09-04: an honest 8.0 on both numbers before anyone but him sees Pulse.

## What Changes

- **Measurement first (wave 0, this PR).** A deterministic inner tier, `task devex:check`, counts
  open audit findings from a new scaffold gate `tests/scaffold/cat10_devex.py` (one
  `xfail(strict=True)` test per finding) and prints `METRIC devex_open_findings=<n>`. It never
  prints a 0-10. The LLM-judged outer tier is preserved as a repeatable protocol under
  `docs/process/devex-audit/` (runbook, frozen agent specs, frozen rubric excerpt, `CHECKSUMS`),
  reachable by `/devex-audit` and `task devex:audit`. A ledger `.planning/devex/loop.jsonl` records
  every merged fix and every audit. The 2026-09-02 reports get the QA corrections applied.
- **Connector composite movers (wave 1).** Kit `__all__` exports fixed; connector authoring
  guide; `templates/connector/` plus `task connector:new NAME=` performing all eight
  registrations; `task install` installs pre-commit hooks; `requires: vars: [CHANGE]` on the nine
  CHANGE-taking targets; `bootstrap.sh` refuses to run in a generated repo; real action SHAs in
  `ci-health.yml` and `auto-heal.yml`; README prerequisites.
- **The M items (wave 2).** `Config.from_env()` collects every missing or invalid variable into
  one message; one canonical connector spec; docs site retitled with mkdocstrings on
  `pulse_core`, every page in the nav; `task test:all` runs the three shell gates and cat7 passes;
  CODEOWNERS, issue and PR templates, a named owner and channel in CONTRIBUTING.
- **Loop rule.** A PR merges only if `task check` is green and `devex_open_findings` does not
  rise. When it reaches 0, the outer audit runs; its top-10 seeds the next change
  (`devex-eight-2`), never an amendment to this one.

Out of scope: editing `docs/process/devex-audit/*` (a protocol change is its own PR); the
`connector-agent` skill (`.planning/reports/2026-09-02-connector-agent-contract.md`); waves
beyond 2, which audit 2 decides. Template-owned paths (`Taskfile.yml`, `bootstrap.sh`,
`scripts/`, `tests/scaffold/`, `.github`) are fixed here first; one batched upstream PR to
repo-ade follows wave 2 (decision with Rob 2026-09-04).

## Capabilities

### New Capabilities
- `devex-measurement`: the two-tier measurement contract: a deterministic count of open audit
  findings that ratchets to zero and fails on regression, and a frozen, checksummed LLM-judged
  audit protocol that is the only source of a 0-10 score.

### Modified Capabilities
- `connector-kit`: the package root exports every name in `__all__`; a scaffold command creates a
  registered, tested connector package; configuration errors report every variable at once.
  (Delta spec written by the doc-updater from wave 1 and 2 HANDOFF.md notes, per AGENTS.md.)

## Impact

- **Code**: `tests/scaffold/cat10_devex.py`, `scripts/devex/check.py`, `Taskfile.yml`
  (`devex:check`, `devex:audit`, later `connector:new`, `install`, `requires:`), `pyproject.toml`
  (`python_files` widened to `cat[0-9]*_*.py`), `pulse_core.connector.__init__`,
  `billing_connector.config`, `bootstrap.sh`, two workflows, `mkdocs.yml`.
- **Docs**: `docs/process/devex-audit/`, `docs/connectors/authoring.md`, README, CONTRIBUTING,
  `.github/CODEOWNERS` and templates, one canonical connector spec.
- **Process**: `.claude/commands/devex-audit.md`; `.planning/devex/loop.jsonl`.
- **Rollback**: every wave is independent PRs; reverting one restores its xfail marker and the
  count rises by one, which the ledger shows. The protocol files are additive.
