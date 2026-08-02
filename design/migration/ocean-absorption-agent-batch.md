# OCEAN → PULSE Absorption — Agent Queue Batch

**Purpose:** Execute the pre-import gate and absorption from the ADR (`ocean-to-pulse-adaptation-plan.md`, rev 2) as Open Engine work orders. One rob-claude session per order, strictly sequential — the dependency chain plus the one-claim-per-run rule guarantees single-agent execution with no parallelism hazards.

**Dependency map:** `OCN-0 → OCN-1 → OCN-2; OCN-0 → OCN-3; (OCN-2 + OCN-3 + DNA-695) → OCN-4 → OCN-5 → OCN-6 → OCN-7`

**Queue mechanics.** Each order below gets a Linear issue titled `[agent instructions] [rob-claude] [task] {slug}` with the `agent-instructions` label, status Agent Todo. Enter them in the sequence above — the queue claims oldest-eligible, so creation order plus the "blocked-on" line in each Context is the sequencing mechanism. Orders whose output is a PR or a destructive action terminate in **Agent Review**, never Agent Done. Two orders (OCN-2, OCN-7) carry an explicit approval gate: the agent must find Rob's approval comment on the issue before acting, else AGENT HUMAN HOLD.

**Before enqueuing — operator setup (Rob, not the agent):**
1. Fill the skill's "Allowed local sources" with the ocean clone path and the future PULSE repo path. It is currently empty, so every task would HUMAN HOLD on first file access.
2. Confirm the agent's GitHub auth is the GitHub App path, with write on `robford-brookai/ocean` and (once created) the org PULSE repo. HIPAA/SOC2 posture — no PAT.
3. DNA-695 (S0.1 PULSE scaffold) is a prerequisite for OCN-4 onward. It is an existing work order — sequence it in the queue between OCN-3 and OCN-4, or complete it by hand and note the repo path on OCN-4.

---

## OCN-0 — Freeze the ocean repo, tag the cut point, write the manifest

### Context
Repo: `robford-brookai/ocean`, local clone per Allowed local sources. Blocked on: nothing — this is the batch entry point. Read the absorption ADR §6.1 and the "should I do pre-work" checklist first (both linked on this issue). The repo is being absorbed into the PULSE monorepo as `packages/ocean` and then archived — this order freezes it and documents what is in it, so later orders operate on a stable, described tree. GitHub writes go through a branch + pull request, never direct to main.

### Task
1. `MANIFEST.md` (repo root, new) — inventory of the tree: top-level directories with one-line purpose each, location of the architecture paper, every deployable (relay, IaC, tooling) with where it deploys, and where any Terraform/IaC state lives (state backend path or "state not found — flagged"). If IaC state references this repo's pipelines, say so explicitly — the PULSE outbox work (S1.1) reads this file to find the bus.
2. `README.md` (edit, top) — freeze notice: "Frozen 2026-07 pending absorption into the PULSE monorepo (see absorption ADR). No new features, producers, or state-derivation code. Hygiene commits only."
3. Git tag `pre-absorption-candidate` on the PR's merge target commit (annotated, message pointing at the ADR). The final `pre-absorption` tag lands in OCN-2 after the history rewrite.
4. Open the PR with MANIFEST + README, link this issue in the description.

### Out of scope
- Any code restructuring or layout changes to fit the uv workspace (that's OCN-4, done by `git-filter-repo` at import)
- Secret/PHI scanning or history rewriting (that's OCN-1/OCN-2)
- Deleting cut-list code (that's OCN-6, inside the PULSE repo, post-import)

### Verification
```
test -f MANIFEST.md && grep -qi "state" MANIFEST.md
grep -qi "frozen" README.md
git tag -l pre-absorption-candidate | grep -q pre-absorption-candidate
gh pr view --json state -q .state | grep -q OPEN
```

### Done means
PR open containing MANIFEST.md and the freeze notice, candidate tag pushed. Terminal status: Agent Review (Rob merges).

---

## OCN-1 — Full-history hygiene scan: secrets, PHI, large objects

### Context
Repo: `robford-brookai/ocean`. Blocked on: OCN-0 merged (scan the frozen tree). Read-only order — no commits, no pushes. `git subtree add` will carry full history into a HIPAA-scoped org monorepo permanently, so anything sensitive must be found now, while rewriting is still cheap. Tools: `gitleaks` and `trufflehog` (install per their docs), plus a git object-size pass. PHI heuristics: scan fixtures and test data for realistic name/DOB/MRN/SSN-shaped content — Synthea-synthetic is fine and should be labeled as such in the report, anything not provably synthetic is a finding.

### Task
1. `reports/ocn1-hygiene-scan.md` (attach to the issue, do not commit to the repo) — three sections:
   a. **Secrets:** `gitleaks detect --source . --log-opts="--all"` and `trufflehog git file://. --only-verified` outputs, deduplicated, each finding with commit hash, path, and a proposed disposition (scrub / false positive / rotate-and-scrub).
   b. **PHI:** grep-based sweep of all historical blobs in fixture/test/data paths for PHI-shaped patterns, each hit classified synthetic / unknown / real-risk.
   c. **Large objects:** all blobs > 1 MB across history (`git rev-list --objects --all` piped through `git cat-file --batch-check`, sorted by size), each with keep / strip disposition.
2. Summary block at top: finding counts by class, and a single recommended `git-filter-repo` invocation (paths and/or replace-text file) that OCN-2 will execute verbatim once approved.
3. If any finding is class real-risk PHI or a verified live credential: post the report, then AGENT HUMAN HOLD naming the finding — do not proceed to Agent Review silently. Live credentials additionally need rotation by Rob before OCN-2 scrubs them.

### Out of scope
- Executing any history rewrite (that's OCN-2, gated on Rob's approval of this report)
- Fixing findings by committing deletions to the tip (tip-only deletion leaves history intact — the whole point is the rewrite)

### Verification
```
gitleaks version && trufflehog --version
test -s reports/ocn1-hygiene-scan.md
grep -q "Recommended git-filter-repo invocation" reports/ocn1-hygiene-scan.md
```

### Done means
Scan report attached to the issue with per-finding dispositions and one executable scrub command. Terminal status: Agent Review (Rob approves dispositions), or Agent Needs Input on real-risk findings.

---

## OCN-2 — Execute the approved history scrub, force-push, re-tag

### Context
Repo: `robford-brookai/ocean`. Blocked on: OCN-1 in Agent Review or later, **and an approval comment from Rob on this issue** quoting or linking the approved scrub command from the OCN-1 report. **Approval gate:** if the approval comment is absent, post AGENT HUMAN HOLD and stop — a force-push that rewrites all history is destructive and irreversible for downstream clones. If OCN-1 found zero scrub-class findings, Rob's approval comment will say "no-op approved": skip tasks 1–3, execute task 4 only, and close.

### Task
1. Fresh mirror clone to a scratch path (`git clone --mirror`), keep the original clone untouched as rollback.
2. Execute exactly the approved `git-filter-repo` invocation from the OCN-1 report against the mirror — no additions, no improvisation. If the approved command fails or the resulting tree diverges from expectation, AGENT FAILED with the log, do not push.
3. Force-push the rewritten history to `robford-brookai/ocean` (all refs). Post the before/after object counts and repo size to this issue as the receipt.
4. Tag `pre-absorption` (annotated) on the new head, push the tag. This is the commit OCN-4 imports.
5. Re-run `gitleaks detect --log-opts="--all"` against the rewritten history — clean run output attached to the issue.

### Out of scope
- Deciding what to scrub (decided in OCN-1, approved by Rob — the agent executes verbatim)
- Any tree-content changes beyond the approved rewrite (freeze is in effect)

### Verification
```
gitleaks detect --source . --log-opts="--all" --exit-code 1; test $? -eq 0
git tag -l pre-absorption | grep -q "^pre-absorption$"
git ls-remote --tags origin | grep -q pre-absorption
```

### Done means
Rewritten history pushed, `pre-absorption` tag on the import commit, post-scrub gitleaks clean. Terminal status: Agent Review.

---

## OCN-3 — Cut-list inventory and ADR §9 reconciliation

### Context
Repo: `robford-brookai/ocean`, read-only. Blocked on: OCN-0 merged (needs MANIFEST). Read the absorption ADR §4.1 (keep/repurpose/forbid table), the ten-row probable-cut list (linked on this issue), and §9 (V1–V11). This order converts "probable" to "confirmed" by walking the actual tree, and produces the do-not-import ledger that OCN-6 executes. No deletions here — deletions happen inside the PULSE repo with visible receipts.

### Task
1. `reports/ocn3-cut-list.md` (attach to the issue) — one row per top-level path in the tree: path, which ADR disposition it falls under (keep / repurpose / cut, citing the §4.1 row or cut-list row), and destination (`packages/ocean/<path>` or "delete in OCN-6").
2. Same report, second section — V1–V11 reconciliation: each verification item marked confirmed / refuted / not-found, one line of evidence each (a path, a file excerpt reference, or "absent").
3. Same report, third section — import shape recommendation: whether plain `--to-subdirectory-filter packages/ocean` suffices (V11 confirmed) or a path-rewrite map is needed, with the map drafted if so.
4. Flag any refuted V-item that invalidates an ADR claim as a bullet list at the top — Rob folds these into the ADR revision, the agent does not edit the ADR.

### Out of scope
- Deleting or moving anything (OCN-6 deletes, OCN-4 moves)
- Editing the ADR (Rob's revision pass, informed by this report)

### Verification
```
test -s reports/ocn3-cut-list.md
grep -c "V1\|V2\|V3\|V4\|V5\|V6\|V7\|V8\|V9\|V10\|V11" reports/ocn3-cut-list.md | awk '{exit ($1>=11)?0:1}'
```

### Done means
Every tree path has a disposition and destination, all eleven V-items reconciled with evidence, import-shape call made. Terminal status: Agent Review.

---

## OCN-4 — Import ocean into the PULSE monorepo as packages/ocean

### Context
Repos: source `robford-brookai/ocean` at tag `pre-absorption`, destination the PULSE monorepo (path per DNA-695 completion note on this issue). Blocked on: OCN-2 (clean history), OCN-3 (import shape approved in review), DNA-695 (scaffold exists, CI green on empty workspace). Import is history-preserving: rewrite paths in a scratch mirror with `git-filter-repo --to-subdirectory-filter packages/ocean` (or the OCN-3 path map), then merge into a PULSE feature branch with `git merge --allow-unrelated-histories`. All destination writes via branch + PR. Do not touch the source repo — it archives in OCN-7.

### Task
1. Scratch mirror of ocean at `pre-absorption`, path-rewritten per the OCN-3 recommendation.
2. PULSE branch `absorb/ocean` — merge the rewritten history in. `git log --follow packages/ocean/<paper path>` must show original ocean commits (history preservation is the acceptance test, not a nice-to-have).
3. `packages/ocean/README.md` (new or edited header) — one paragraph: this is the distribution subsystem (relay, envelopes, archive/replay, bus IaC), absorbed per the absorption ADR, record-versus-feed pointer to the ADR.
4. Copy the absorption ADR into the monorepo ADR log per rob-repo convention (`docs/adr/` numbering), status Accepted, superseding note referencing the ocean paper's location at `packages/ocean/<paper path>`.
5. Open the PR. Description: source tag, filter-repo invocation used, commit count imported, link to OCN-3 report. CI is expected red or skipped for the imported package at this point — conformance is OCN-5. State that expectation in the PR description so review reads it as intended.

### Out of scope
- Workspace wiring, lint/type/test conformance (that's OCN-5)
- Deleting cut-list paths (that's OCN-6 — import everything, cut visibly afterward)
- Archiving the source repo (that's OCN-7)

### Verification
```
git log --oneline --follow packages/ocean | wc -l | awk '{exit ($1>1)?0:1}'
test -f packages/ocean/README.md
ls docs/adr/ | grep -qi "absorb"
gh pr view absorb/ocean --json state -q .state | grep -q OPEN
```

### Done means
PR open on the PULSE repo containing the full ocean history under `packages/ocean` plus the ADR log entry. Terminal status: Agent Review (Rob merges).

---

## OCN-5 — Conform packages/ocean to the monorepo standard

### Context
Repo: PULSE monorepo, package boundary `packages/ocean` only. Blocked on: OCN-4 merged. Read CLAUDE.md first, then the rob-repo conventions the scaffold emitted (ruff, pyright, pytest-per-package, uv workspace membership). This is conformance by inheritance: wire the package into the existing standards, fix what they flag, change no behavior. If the imported code is not Python (IaC, schemas, tooling), conform what applies and register the rest with the repo's format/lint hooks (yaml, terraform fmt) rather than forcing the Python toolchain onto it.

### Task
1. Root `pyproject.toml` / workspace config — add `packages/ocean` as a workspace member (if Python code exists there); otherwise register its paths in the relevant lint/format hooks.
2. `packages/ocean/pyproject.toml` — package metadata per the monorepo template (if applicable).
3. Fix ruff and pyright findings within `packages/ocean` — mechanical fixes only. Any fix requiring a behavior judgment: list it in the PR description as deferred, do not guess.
4. `packages/ocean/tests/` — ensure the existing test suite runs under pytest-per-package. Port test invocations, do not write new coverage (freeze is still morally in effect — no new features).
5. CI green on the branch, PR opened.

### Out of scope
- New features, refactors, or behavior changes in the imported code
- Deleting cut-list paths (OCN-6 — conform them too if trivial, or `ruff`-exclude them with a comment citing OCN-6)
- Envelope extension or catalog wiring (that's the S0.2 catalog work order territory)

### Verification
```
ruff check packages/ocean && pyright packages/ocean
uv run pytest packages/ocean
gh pr checks --watch --fail-fast
```

### Done means
CI green with packages/ocean inside the workspace, zero behavior changes, deferred-judgment list in the PR. Terminal status: Agent Review.

---

## OCN-6 — Execute the cut list inside the monorepo, with receipts

### Context
Repo: PULSE monorepo, `packages/ocean`. Blocked on: OCN-5 merged, and the OCN-3 report approved in review (the cut list is Rob-approved by that review — no separate gate needed, but re-read the approved report before acting; if review comments amended any disposition, the comments win). Deletions happen here, post-import, so the monorepo history shows what was cut and why — that is the audit design, per the ADR's do-not-pre-delete rule.

### Task
1. One commit per cut-list row (or per coherent group as marked in the OCN-3 report): delete the path(s), commit message `cut(ocean): <path> — <ADR cut-list row #> <one-line reason>`.
2. Remove now-dead references: imports, CI includes, hook registrations that pointed at deleted paths.
3. `docs/adr/` — append a short "cuts executed" note to the absorption ADR entry (date, commit range, pointer to OCN-3 report). Do not rewrite the ADR body.
4. CI green, PR opened with the full cut manifest in the description.

### Out of scope
- Cutting anything not on the approved OCN-3 report — a newly discovered candidate gets a comment on this issue for the next batch, not a deletion
- Refactoring survivors to fill gaps the cuts exposed (if a keep-path depended on a cut-path, AGENT BLOCKED with the specific dependency — that is a cut-list defect to resolve on the issue, not an improvisation)

### Verification
```
git log --oneline | grep -c "^.* cut(ocean):" | awk '{exit ($1>=1)?0:1}'
ruff check packages/ocean && pyright packages/ocean
uv run pytest packages/ocean
gh pr checks --watch --fail-fast
```

### Done means
Every approved cut executed as an attributed commit, CI green, no unapproved deletions. Terminal status: Agent Review.

---

## OCN-7 — Supersede the paper and archive the source repo

### Context
Repo: `robford-brookai/ocean`. Blocked on: OCN-6 merged, **and an approval comment from Rob on this issue** ("archive approved"). **Approval gate:** archiving is external-facing and semi-irreversible — absent the comment, AGENT HUMAN HOLD. The supersession notice text is in the absorption ADR §7 — use it verbatim.

### Task
1. Final PR to ocean: replace `README.md` body with the §7 supersession notice verbatim, plus one line: "Code and full history: `packages/ocean` in the PULSE monorepo (imported at tag `pre-absorption`)." Rob merges.
2. After merge: `gh repo archive robford-brookai/ocean --yes`.
3. Post the closing receipt on this issue: archive timestamp, final commit hash, PULSE import PR link, and one line confirming the org-transfer remediation list no longer includes ocean (per ADR action item 7).

### Out of scope
- Deleting the repo (archive only — history redundancy is the point)
- Touching Linear remediation issues for the other personal-account repos (brook-status-reporter, ringer, tide-forecast keep the transfer + retrofit path)

### Verification
```
gh repo view robford-brookai/ocean --json isArchived -q .isArchived | grep -q true
gh repo view robford-brookai/ocean --json description,url >/dev/null
```

### Done means
Source repo archived read-only with the supersession notice as its face, closing receipt on the issue. Terminal status: Agent Review — this closes the batch.

---

## Batch notes

- **Sequencing is structural, not honorary.** Every Context carries a "blocked on" line, the queue claims one issue per run, and OCN-2/OCN-7 hard-gate on approval comments. The worst-case failure of an eager agent is claiming OCN-3 before OCN-1 finishes — harmless, both read the same frozen tree.
- **Human touchpoints, in order:** merge OCN-0 PR → approve OCN-1 dispositions (+ rotate any live credentials) → approval comment on OCN-2 → approve OCN-3 report (+ fold refuted V-items into the ADR) → complete/confirm DNA-695 → merge OCN-4 → merge OCN-5 → merge OCN-6 → approval comment on OCN-7 → merge final PR. Ten touches, each readable from a PR page or a one-line comment.
- **ADR linkage:** OCN-0 through OCN-3 are the "pre-import gate" from ADR action item 3. OCN-4/OCN-5 are §6.1 steps 1–3. OCN-6 executes the do-not-import list. OCN-7 is §6.1 steps 4–5.
