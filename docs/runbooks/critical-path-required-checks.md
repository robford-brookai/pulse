# Runbook — critical-path required checks (critical-path-verification task 3.1)

The attended repository-administration session that turns the two evidence-bearing CI jobs into
required checks on `main`. Everything before the last step is read-only or local; the last step
changes branch protection and is the one thing only a repository admin does. Receipts go on the
tracking GitHub issue, never as a file under `handoffs/`.

Why a session and not YAML: a workflow file cannot make itself required. Committing the job is
task 1.2 (#472) and 2.1 (#477); making it required is a repository setting, verified against the
job names that actually ran (design.md decision 2: never claim a rule was configured by committing
YAML).

## The two checks

| Workflow (`name:`) | Job (`jobs.<id>`) | Check context GitHub reports | What it proves |
|---|---|---|---|
| `Main` | `quality` | `quality` | `task check`, which now runs `task test:critical` in required mode: the six `@pytest.mark.critical` Postgres-backed invariant tests, evidence in the `critical-gate-evidence` artifact |
| `Transport integration` | `transport` | `transport` | `task test:transport` in required mode against LocalStack: the relay's dropped-delivery, duplicate and redrive cases, evidence in the `transport-gate-evidence` artifact |

The check context is the **job id**, not the workflow name. `quality` is already required
(`strict: true`); `transport` is not yet.

## Prerequisites

- `gh` authenticated as a repository admin (step 5 needs it; steps 1–4 need read access only).
- A main checkout at or after #477.

## Steps

1. **Pick the commit and confirm both workflows ran on it.**
   ```bash
   SHA=$(git rev-parse origin/main)
   gh run list -R robford-brookai/pulse --commit "$SHA" \
     --json name,status,conclusion,databaseId --jq '.[] | "\(.name) | \(.status) | \(.conclusion) | \(.databaseId)"'
   ```
   PASS: one `Main` run and one `Transport integration` run, both `completed | success`, both for
   the same `$SHA`. Record the two run ids.

2. **Download the evidence and read the counts.**
   ```bash
   gh run download <main run id> -R robford-brookai/pulse -n critical-gate-evidence -D /tmp/cge
   gh run download <transport run id> -R robford-brookai/pulse -n transport-gate-evidence -D /tmp/tge
   python3 -c 'import json; d=json.load(open("/tmp/cge/critical-gate.json")); print(d["mode"], d["counts"], d.get("postgres_version"))'
   python3 -c 'import json; d=json.load(open("/tmp/tge/transport-gate.json")); print(d["mode"], d["counts"], [c["name"] for c in d.get("cases", [])])'
   ```
   PASS: both `mode` are `required`; critical `counts` show `passed` equal to the number of
   `@pytest.mark.critical` tests in the tree (six at #472) with `skipped: 0`; transport `counts`
   show `failed: 0, errors: 0, skipped: 0` and `cases` names every collected test.

3. **Prove the gates fail closed when a prerequisite is missing** (local, no network).
   ```bash
   PULSE_PG_BINDIR=/nonexistent PULSE_CRITICAL_PG_MODE=required \
     uv run python scripts/critical_gate_evidence.py packages/pulse-ledger/tests packages/pulse-core/tests
   PULSE_TRANSPORT_MODE=required \
     uv run python scripts/transport_gate.py packages/pulse-ledger/tests/integration   # with Docker stopped
   ```
   PASS: each exits non-zero and names the missing prerequisite (the Postgres binaries; the
   Docker daemon the LocalStack fixture needs) rather than passing with zero tests. Paste the two
   summary lines on the issue.

4. **Verify the required contexts against the job names that ran.**
   ```bash
   gh api repos/robford-brookai/pulse/branches/main/protection/required_status_checks --jq '{strict, contexts}'
   gh run view <transport run id> -R robford-brookai/pulse --json jobs --jq '.jobs[].name'
   ```
   PASS: the job name printed for the transport run is exactly `transport`, and the current
   `contexts` list is `["quality"]` with `strict: true` (the state before this session).

5. **Make `transport` required** (repository admin, attended).
   ```bash
   gh api -X PATCH repos/robford-brookai/pulse/branches/main/protection/required_status_checks \
     --input - <<'JSON'
   {"strict": true, "contexts": ["quality", "transport"]}
   JSON
   gh api repos/robford-brookai/pulse/branches/main/protection/required_status_checks --jq '{strict, contexts}'
   ```
   PASS: `contexts` is `["quality", "transport"]`, `strict` stays `true`. Open a trivial PR (or
   look at the next worker PR) and confirm the merge box lists both checks as required.

6. **Post the receipt** on the tracking issue: the commit sha, the two run ids, the two evidence
   summaries from step 2, the two fail-closed lines from step 3, and the before/after `contexts`
   from steps 4 and 5. Counts and names only.

## Runbook assertions (task 3.1's tests)

- Mandatory suites ran: critical `passed` equals the marked count, transport `cases` is non-empty.
- No required skips: both `skipped` counts are `0` in required mode.
- Required checks match actual workflow names: `contexts` equals the set of job ids that ran,
  `{quality, transport}`.

## Rollback

`gh api -X PATCH .../required_status_checks --input -` with `{"strict": true, "contexts": ["quality"]}`
restores the prior rule. Nothing else in this session changes state.
