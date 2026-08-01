# ADE Execution Layer Comparison: Orca vs operator-oss

Deep-research report, 2026-07-31. Method: 6 search angles, 17 sources fetched,
82 claims extracted, 25 adversarially verified (3-vote panels) — 22 confirmed,
3 refuted, 0 unverified. 100 agents total.

**Candidates**

| | [stablyai/orca](https://github.com/stablyai/orca) | [iishyfishyy/operator-oss](https://github.com/iishyfishyy/operator-oss) |
|---|---|---|
| Created | 2026-03-17 | 2026-07-13 |
| License | MIT | Apache-2.0 |
| Stars / forks | 34,582 / 2,413 | 129 / 18 |
| Model | Desktop/mobile/VPS ADE, any coding agent | Local-first web app, Claude Code or Codex |
| Forks (ours) | robford-brookai/orca | robford-brookai/operator-oss |

## Recommendation

**Wire Orca (stablyai/orca) in as repo-ade's execution layer.** It positively
satisfies all five required capabilities with binary-verified evidence; the
disqualifying capability for operator-oss (scriptable task creation) is
unconfirmed.

Implementation guardrails:

- Pin a stable Orca release — daily cadence means CLI flags and JSON shapes move.
- `dispatch_tasks.py` should tolerate both JSON result shapes
  (`result.agentTerminalHandle` vs `result.startupTerminal.handle`).
- Ensure `orca serve` or the Orca app is running before dispatch.
- Discover worktree paths via `orca worktree list --json`, not a hardcoded root.

## Confirmed findings

### 1. Orca exposes a fully scripted, headless task-creation surface — high confidence (3-0 × 5 merged claims)

`orca worktree create --name <name> --agent <id> --prompt "<task>" --setup run
--json` creates an isolated worktree, launches an agent, injects an arbitrary
prompt, and emits machine-readable JSON. `orca serve` runs the runtime
headlessly — the claimed refutation that the CLI requires a running GUI was
itself refuted 0-3. Verified against official docs and the installed binary
(`/opt/homebrew/bin/orca --help`), whose help text documents `--agent`,
`--prompt` ("sends initial work to that agent"), `--setup run|skip|inherit`,
`--repo` selectors (`id:`/`name:`/`path:`), and `--json`.

Sources: [CLI reference](https://www.onorca.dev/docs/cli/reference),
[CLI overview](https://www.onorca.dev/docs/cli/overview),
[orchestration docs](https://www.onorca.dev/docs/cli/orchestration),
[worktree model](https://www.onorca.dev/docs/model/worktrees),
[README](https://github.com/stablyai/orca), local binary help output.

### 2. Orca provides orchestration primitives beyond one-shot creation — high confidence (3-0 × 3 merged claims)

`orca orchestration task-create --spec "<instruction>" --json` creates tasks
with arbitrary instruction strings; `orca terminal create --worktree <sel>
--command <cmd>` and `orca terminal send --text --enter` inject text into agent
terminals; `worker-start --task <id> --worktree <sel> --agent <id>` (newest
releases only) dispatches a supervised worker with a defined `worker_done`
completion signal. Caveat: the locally installed build (2026-07-25) lacks
`worker-start` and uses `task-create` + `dispatch --inject` for the same effect.

Sources: [orchestration docs](https://www.onorca.dev/docs/cli/orchestration),
[CLI overview](https://www.onorca.dev/docs/cli/overview),
`src/cli/specs/orchestration-worker-specs.ts` in the repo, local binary help.

### 3. Orca worktrees are real git worktrees at plain filesystem paths — high confidence (3-0 × 3 merged claims)

Docs: "every task gets its own on-disk copy of the repo via `git worktree`."
Empirically confirmed: local `orca worktree list` prints plain absolute paths
readable by any script, with `--json` support. This satisfies
`collect_handoffs.py`'s need to scan worktrees for HANDOFF.md. The default
worktree root is not formally documented (observed under
`~/orca/workspaces/<repo>/<task>` and configurable placements) — rely on
`orca worktree list --json`.

Sources: [worktree model](https://www.onorca.dev/docs/model/worktrees),
[README](https://github.com/stablyai/orca), local `orca worktree list` output.

### 4. Orca is agent-agnostic — high confidence (3-0 × 3 merged claims)

Launches Claude Code, Codex, or ~30 named agents per worktree (via `--agent`),
plus arbitrary custom CLI agents registered by name, binary/command, default
args, and an optional startup hook. Minor caveat: custom agents lose live
working/idle indicators unless they emit OSC title updates.

Sources: [CLI reference](https://www.onorca.dev/docs/cli/reference),
[custom CLI agents](https://www.onorca.dev/docs/agents/custom-cli),
[Claude Code in Orca](https://www.onorca.dev/docs/agents/claude-code).

### 5. Orca satisfies the no-API-key requirement — high confidence (3-0 × 4 merged claims)

Reuses local `~/.claude` credentials from a one-time terminal login ("Orca
picks up ~/.claude automatically — no extra config needed"); Claude Code
defaults to subscription OAuth for Pro/Max users. ToS check: Anthropic's
Feb 2026 restriction bans subscription OAuth outside Claude Code/Claude.ai, but
Orca spawns the official `claude` CLI per worktree, which falls inside the
carve-out. Pre-release v1.4.163-rc.3 (2026-07-31) added headless account
management (`orca account add` / `account list`) capturing OAuth logins, not
API keys (RC-only, host-local).

Sources: [Claude Code in Orca](https://www.onorca.dev/docs/agents/claude-code),
[Claude Code auth docs](https://code.claude.com/docs/en/authentication),
[releases](https://github.com/stablyai/orca/releases),
[PR #9177](https://github.com/stablyai/orca/pull/9177).

### 6. Orca's maturity risk was overstated — high confidence (3-0 × 2 merged claims)

True open issues are ~1,318 (1,447 closed, ~52% close rate). The 2,795 figure
is GitHub's `open_issues_count`, which conflates open PRs (1,318 + 1,475 =
2,793, matching exactly). Stable releases ship roughly daily (v1.4.147 →
v1.4.162 over 11 days). Combined with 34,582 stars and same-day pushes: a
large, very actively maintained project — but a fast-moving target repo-ade
should pin against.

Sources: [issue tracker via GitHub search API](https://github.com/stablyai/orca/issues),
[releases](https://github.com/stablyai/orca/releases).

### 7. operator-oss: isolation and subscription confirmed, scriptability unconfirmed — high confidence (3-0 × 2 merged claims)

README verbatim: "Each task is its own agent session — Claude Code or Codex —
in its own git worktree" and "Runs on your Max/Pro login — no API key, no
per-token billing." But no confirmed claim establishes a CLI or REST surface
for programmatic task creation, and the README documents neither worktree disk
location nor external-script access. Important ambiguity: the claim that
operator-oss documents *only* web-UI task creation was refuted 0-3, so some
programmatic surface may exist (likely in `docs/ARCHITECTURE.md`,
`docs/SELF_HOSTING.md`, or source) — but it remains unverified, whereas Orca's
is proven against a shipped binary.

Source: [operator-oss README](https://github.com/iishyfishyy/operator-oss).

### 8. Recommendation synthesis — derived

Orca positively satisfies all five required capabilities (scripted worktree
creation, per-task prompt injection, parallel Claude Code sessions on
subscription login, diff review/merge in-app plus standard git tooling,
filesystem-readable worktrees). operator-oss satisfies at most three, with the
disqualifying capability unconfirmed, a 129-star community, and a July 2026
creation date. Orca's orchestration layer (task DAGs, `worker_done`, dispatch)
also offers a native upgrade path beyond repo-ade's thin-glue scripts.

## Refuted claims

| Claim | Vote | Source |
|---|---|---|
| Orca CLI requires the desktop GUI running; not fully standalone | 0-3 | [CLI overview](https://www.onorca.dev/docs/cli/overview) — `orca serve` is headless |
| Users actively rely on Orca CLI batch automation (per a 2026-07-31 feature request) | 1-2 | [issues](https://github.com/stablyai/orca/issues) |
| operator-oss documents only web-UI task creation | 0-3 | [operator-oss README](https://github.com/iishyfishyy/operator-oss) — a programmatic surface may exist |

## Caveats

- Most Orca evidence is vendor documentation, but nearly every capability claim
  was independently corroborated by inspecting the installed binary.
- Version sensitivity: `orchestration worker-start` exists only in the newest
  releases; `orca account add` is RC-pre-release only; JSON output shapes vary
  across runtime versions.
- The operator-oss picture is incomplete — only its README was verified; the
  comparison is asymmetric in research depth, though the maturity and
  verification gaps stand regardless.
- One closed upstream issue reported `claude -p` headless mode billing some Max
  users at API rates.
- All facts are a 2026-07-31 snapshot of two fast-moving projects.

## Open questions

1. Does operator-oss expose any CLI/REST/headless interface for programmatic
   task creation, and where do its worktrees live on disk?
2. What is Orca's default worktree root, is it configurable per repo, and
   should the glue scripts discover paths exclusively via
   `orca worktree list --json`?
3. How stable is Orca's CLI flag and JSON-output contract across its ~daily
   release cadence — version-pinned install vs schema-tolerant parsing?
4. Should repo-ade eventually replace the HANDOFF.md convention with Orca's
   native orchestration protocol (`task-create`/`dispatch`/`worker_done`), or
   keep the tool-agnostic file-based handoff to avoid lock-in?

## Sources

| URL | Quality | Angle |
|---|---|---|
| https://www.onorca.dev/docs/cli/reference | primary | Orca CLI surface and prompt injection |
| https://www.onorca.dev/docs/cli/overview | primary | Orca CLI surface and prompt injection |
| https://www.onorca.dev/docs/model/worktrees | primary | Orca CLI surface and prompt injection |
| https://www.onorca.dev/docs/cli/orchestration | primary | Orca CLI surface and prompt injection |
| https://github.com/stablyai/orca | primary | Orca CLI surface and prompt injection |
| https://www.onorca.dev/docs/agents/custom-cli | primary | Orca CLI surface and prompt injection |
| https://github.com/nektos/act/issues/6074 | forum | Worktree filesystem layout and external access |
| https://www.onorca.dev/docs/agents/claude-code | primary | Subscription login without API key |
| https://code.claude.com/docs/en/authentication | primary | Subscription login without API key |
| https://github.com/stablyai/orca/issues | primary | Reliability and contrarian signal |
| https://vibecodinghub.org/blog/orca-review | blog | Reliability and contrarian signal |
| https://github.com/stablyai/orca/releases | primary | Reliability and contrarian signal |
| https://github.com/stablyai/orca/issues/10425 | forum | Reliability and contrarian signal |
| https://www.ycombinator.com/companies/stably-ai-orca | secondary | Reliability and contrarian signal |
| https://github.com/iishyfishyy/operator-oss | primary | Ecosystem fit |
| https://mcpservers.org/agent-skills/stablyai/orca-cli | secondary | Ecosystem fit |
| https://getoperator.dev/ | primary | Ecosystem fit |
