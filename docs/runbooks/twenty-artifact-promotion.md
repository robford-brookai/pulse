# Runbook: twenty-artifact-promotion

Operator procedure for promoting the Twenty metadata artifact from one instance to the next —
dev → staging → prod. The whole procedure rests on one property: **promotion is the same file,
the next target.** `packages/twenty-app/artifact/operations.json` is a reviewed, committed
operation set with no environment in it; the only thing that changes between environments is
which credential pair `--target` resolves (design Decision 4). Nothing regenerates during a
promotion, and nothing is edited to fit an environment.

Rollback is the same mechanism read backwards: re-apply the previous artifact. There is no undo
verb, because the deploy step has no delete verb.

The Twenty Metadata API this consumes is registered in `docs/contracts/consumes.md`.

## Before you promote

Two preconditions, both checkable offline:

1. `task check` is green on the commit you are promoting. `twenty:validate` inside it proves the
   committed artifact re-renders byte-identically from the catalog, its UID map is complete, and
   its options match the generated TypeScript — a drifted artifact never reaches a target.
2. The target's credential pair is set: `PULSE_TWENTY_<TARGET>_URL` and
   `PULSE_TWENTY_<TARGET>_TOKEN`, resolved from the environment and never from code. An empty
   value counts as missing and the deploy refuses by name rather than applying with garbage.

Record the artifact checksum you are promoting before you start:

```bash
uv run python -c "from pathlib import Path; from pulse_core.twenty_deploy import artifact_checksum; from pulse_core.twenty_metadata import ARTIFACT_PATH; print(artifact_checksum(ARTIFACT_PATH))"
```

The same checksum has to appear in the receipt from every target. Two targets with matching
checksums is what "one artifact promotes everywhere" means in evidence rather than in prose.

## Promote

```bash
uv run python -m pulse_core.twenty_deploy --target staging --dry-run   # the plan, nothing sent
task twenty:deploy TARGET=staging
task twenty:verify TARGET=staging
```

1. **Plan and apply** — `twenty:deploy` validates the artifact, reads the target's current state,
   and replays the operation set idempotently: create-if-absent keyed on `universalIdentifier`,
   update-if-drifted, never delete. Applying to an instance that already carries the artifact is
   all no-ops; a no-op is never sent.
2. **Verify by read-back** — `twenty:verify` asserts every artifact operation is present on the
   target under its mapped `universalIdentifier`, then re-applies and asserts the receipt reports
   zero creates and zero updates. It exits nonzero on any mismatch, and the JSON it prints —
   operation names, counts, artifact checksum — is the receipt to attach to the promotion record.
   It carries no workspace data and no response bodies, so it is safe to attach anywhere.
3. **Verify the projection behaviour** (dev, or any environment where synthetic records are
   acceptable):

   ```bash
   task twenty:verify:live TARGET=dev
   ```

   Runs the five projection cases against the live server with the real Core API client, creates
   its synthetic fixtures under a per-run identifier, and deletes them again. **Synthetic data
   only — never run this against an environment holding real records.**

Attach both receipts to the change's Linear parent. A promotion without a read-back receipt is
an unverified promotion.

## Rollback

Rollback is a re-apply of the previous artifact, not an undo:

```bash
git show <previous-commit>:packages/twenty-app/artifact/operations.json > /tmp/previous-operations.json
uv run python -m pulse_core.twenty_deploy --target staging --artifact /tmp/previous-operations.json
uv run python -m pulse_core.twenty_verify --target staging --artifact /tmp/previous-operations.json
```

What this does and does not do, stated plainly because the difference matters under pressure:

- **Reverts field and option changes**: a field whose type, label, default, or option set changed
  is updated back to what the previous artifact declares.
- **Does not remove what the newer artifact added.** The deploy step never deletes, so an object
  or field introduced by the artifact you are rolling back *from* stays on the target, unused.
  Removing it is a deliberate, separately reviewed act against the instance — never a rollback
  side effect.
- **Does not restore records.** Metadata only. A rollback that narrows an option set leaves
  records holding the removed value; check for them before narrowing, not after.

An option value removed from the catalog is therefore the one promotion shape that is not freely
reversible. Treat it as a breaking catalog release (`docs/runbooks/catalog-release.md`) and land
the record migration first.

## Two things the live server does that the artifact does not say

Both were found on first contact with the dev instance (2026-08-16/17) and will surprise anyone
reading a raw read-back against the committed artifact:

- **SELECT option values are stored UPPER_SNAKE_CASE.** The catalog's `referral.received` is
  stored as `REFERRAL_RECEIVED`. The encoding is applied at the transport boundary — the deploy
  plan on the way out, the live Core API client on the way in — and never written back into repo
  files. The catalog stays the only vocabulary.
- **Objects carry an auto-provisioned `name` field.** Twenty provisions it; the artifact does not
  declare it, and it is not drift. A `universalIdentifier` is immutable, so never try to adopt or
  re-key an existing field onto it.

## If a promotion fails

- **Validation refused before any operation** — the artifact is stale or broken. Fix it on a
  branch with `task twenty:gen` and `task check`; nothing reached the target.
- **A failed operation mid-apply** — the receipt names the operation and the counts applied
  before it, and carries no response body by construction. The apply is idempotent, so the fix is
  to correct the cause and re-run the same command; already-applied operations become no-ops.
- **Read-back reports something missing** — the re-apply is skipped deliberately: a verification
  script detects, it never repairs. Re-run `twenty:deploy`, then verify again.
