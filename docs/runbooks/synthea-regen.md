# Runbook: synthea-regen

Operator procedure for the weekly staging population regeneration
(`.github/workflows/synthea-regen.yml`, `task synthea:regen`). The workflow generates a
deterministic synthetic population from the checksum-pinned Synthea JAR and verifies the result
against the committed manifest at `packages/synthea-seed/manifests/<profile>.manifest.json`.
Divergence is a failure, never a refresh.

Everything here is synthetic by construction — Synthea generates people who do not exist. No
step of this procedure touches PHI, and the uploaded artifacts carry none.

## Who authors the manifest

The CI runner, and only the CI runner. `synthea-pin.yaml`'s header names it "the
manifest-authoring platform of record", and that is the binding statement: JVM floating-point
and iteration-order determinism holds within a platform, not across them, so a manifest authored
on a workstation would fail verification on `ubuntu-latest` forever. Re-pinning is still an
explicit, reviewed act — it just happens on the runner, through a dispatch input, and lands as a
committed manifest diff in a PR.

## Dispatching a run

Verification run (what the Monday schedule does, and what you dispatch to re-check on demand):

```bash
gh workflow run "Synthea regen" --ref main
```

Re-pin run — authors a new manifest from the generated tree instead of verifying it:

```bash
gh workflow run "Synthea regen" --ref <branch> -f repin=true
```

Then poll and watch. A 50k staging run takes roughly 40 minutes of generation on top of a few
minutes of setup:

```bash
gh run list --workflow "Synthea regen" --branch <branch>
gh run watch <run-id>
```

`repin=true` is a `workflow_dispatch` input only. A scheduled run leaves it unset and always
verifies, so the schedule can never quietly rewrite the receipt.

## The re-pin procedure

Re-pin when, and only when, the pin itself changed — a new JAR version, a new seed, a changed
module property, a changed population — or when bootstrapping a profile that has no manifest yet.

1. Branch, and make the pin edit in
   `packages/synthea-seed/src/synthea_seed/config/synthea-pin.yaml`. Editing that file *is* the
   re-pin decision; it invalidates every existing manifest by construction. Push the branch.
2. Dispatch with `-f repin=true` against your branch (command above) and wait for it to go green.
3. Download the manifest the run authored:

   ```bash
   gh run download <run-id> -n synthea-staging-manifest
   ```

4. Commit it as `packages/synthea-seed/manifests/staging.manifest.json`, review the diff (below),
   and push.
5. Dispatch once more against the same branch **without** `repin` and confirm the run is green.
   That verification run is the proof the manifest is reproducible; a re-pin PR without one has
   only asserted the manifest, not tested it.
6. Open the PR carrying the pin edit, the manifest, and both run URLs.

Nothing is ever written back to the branch by the workflow. The manifest reaches `main` as an
ordinary reviewed commit.

## Reviewing a manifest diff

The manifest is JSON: `format`, `profile`, `synthea_version`, `seed`, a `files` map of
POSIX-relative path to sha256, and `top_hash` — one hash over the sorted `(path, sha256)` pairs,
so it is order-independent and changes if any file does.

What to look for:

- **`top_hash` changed, `seed` and `synthea_version` unchanged, `files` count unchanged, every
  hash different.** Non-determinism has leaked into generation — wall-clock time, an unpinned
  property, a JVM difference. Do not merge; the pin is the bug.
- **`files` count changed.** The population size or the exporter set changed. Reconcile against
  the `synthea-pin.yaml` diff in the same PR: an unexplained count change means the properties
  no longer say what the manifest shows.
- **`synthea_version` or `seed` changed with a wholly different `files` map.** Expected, and the
  reason for the re-pin. Confirm the new values match the pin edit exactly.
- **A handful of paths changed and the rest identical.** Suspicious for a deterministic
  generator — check whether an overlay or a property touched only part of the tree.

`git diff --stat` on the manifest is the fastest first read: the line count of the `files` map
is the population's file count.

## What a failed run looks like

The run step exits nonzero and the message names the failure class. Read the last lines of
`gh run view <run-id> --log-failed`:

- `no committed manifest at manifests/staging.manifest.json ... rerun with REPIN=1` — the
  profile has never been pinned. This is the bootstrap case: run the re-pin procedure above. It
  is *not* fixed by re-running the schedule, which is why five consecutive Monday runs failed
  identically (`docs/ci-lessons.md`, 2026-09-08).
- `output for profile 'staging' diverges from manifests/staging.manifest.json:` followed by
  `changed:` / `missing:` / `unexpected:` lines, then exit 1. Real drift. Something changed that
  the pin does not describe. Diagnose before re-pinning — a re-pin here launders a defect into
  the receipt.
- `synthea-v3.3.0.jar: sha256 ... does not match pinned ...` — the cached or downloaded JAR is
  not the pinned one. The cache is keyed on the pin file and the checksum is re-verified on every
  run, so this means the upstream release artifact changed. Stop and investigate; do not update
  the pinned sha256 to match whatever arrived.
- `could not download the pinned JAR from ... after 3 attempts` — network failure, already
  retried with backoff. Re-dispatch.
- `synthea generation for profile 'staging' exited <n>` — the JVM died. Most often heap: the
  staging profile passes `-Xmx6g` (`generation_command` in `regen.py`) sized for a standard
  16 GB runner. A larger population needs that constant revisited, and the population itself is
  a design decision recorded in `synthea-pin.yaml` and
  `design/delivery/pulse-runtime-readiness.md` §2.1 — never change it silently to make a run fit.

Job-level `timeout-minutes: 120` bounds the whole thing; a run that hits it was hung, not slow.

## Running it locally

Java 17+ and roughly an hour for staging; `dev` (500 patients) is the inner-loop profile.

```bash
task synthea:regen PROFILE=dev
```

Local verification of `staging` may diverge from the committed manifest for platform reasons
alone — that is expected and is not evidence of drift. `REPIN=1` locally is for exploring a pin
edit before dispatching; the manifest that gets committed is always the one CI authored.
