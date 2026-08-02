# PULSE S1 Work Orders — Verdict Writer, Scheduler/Sweeps, Identity Resolution

**Dependency map:** `S0.2 → S1.1 → {S1.2, S1.3, S1.4}` — the three are mutually independent and parallel-safe after S1.1 merges. Queue titles: `[agent instructions] [rob-claude] [task] {slug}` with the `agent-instructions` label, per the agent queue pattern. All three terminate in Agent Review.

**Shared context for all three:** PULSE monorepo (path per DNA-695 completion note). Read CLAUDE.md first. S1.1 provides the ledger schema, the command API client module (`packages/pulse-core/client.py` — confirm actual path on the S1.1 PR and pin it on each issue before enqueuing), command type definitions generated from the catalog (S0.2), and the idempotency-key convention (D16: `{writer_id}:{sha256(subject, command_type, payload, logical_time)}`). Auth: per-service credentials per D15 — credential names in Context, values from the environment, never in code or fixtures. No live network calls in any test suite.

---

## S1.2 — Build the verdict declare-back writer

### Context
Package: `packages/verdict-relay`. Depends on: S1.1 (command API client, `declare_verdict` command type, idempotency convention), S0.2 (catalog-generated verdict enums). This component closes the I3 loop: dbt computes verdict marts in Snowflake, this service reads them and declares each verdict to the ledger as an attributed command (actor = the writer's service identity, carrying model `rule_version`, `as_of`, and input lineage from the mart row). It is a new component on the single write path — idempotency and ordering are the whole job. Mart contract (from the dbt side, fixture-pinned in this issue): one row per (subject, verdict_type, run), columns `subject_id, verdict_type, outcome, reason, rule_version, as_of, lineage_ref, computed_at`. Trinary outcomes per the object model §3: `positive | negative | indeterminate` with mandatory reason on `indeterminate`. Ordering rule: per subject, declare in `as_of` order, and never declare a verdict older than the subject's latest declared `as_of` (stale runs are skipped and counted, not errored). Runs are batch, cursor-based on `computed_at`, resumable.

### Task
1. `packages/verdict-relay/src/verdict_relay/mart_reader.py` — cursor-based reader over the verdict mart contract, ordered (subject, as_of), cursor persisted via the command API's writer-state facility from S1.1 (confirm path) so a crashed run resumes without re-reading.
2. `packages/verdict-relay/src/verdict_relay/declarer.py` — maps a mart row to a `declare_verdict` command with idempotency key per the D16 convention, skips stale rows per the ordering rule, classifies command API responses: committed, replayed (idempotent hit), rejected (transition illegal — counted and logged with the ledger's reason, never retried), transient error (retried with backoff, 5 attempts, then run fails with the failing row identified).
3. `packages/verdict-relay/src/verdict_relay/run.py` — batch entrypoint: read → declare → emit a run receipt (counts: declared, replayed, skipped-stale, rejected, failed) as structured logs with `service:verdict-relay` tags and a Datadog-parsable summary line.
4. `packages/verdict-relay/pyproject.toml` — workspace member per the monorepo template.
5. `packages/verdict-relay/tests/fixtures/` — recorded mart rows (JSON) covering: normal declare, idempotent replay, out-of-order stale run, illegal transition rejection, indeterminate-with-reason, indeterminate-without-reason (must fail validation before the API call). NO live Snowflake or API calls — command API faked at the client boundary.
6. `packages/verdict-relay/tests/test_ordering.py` — property-based test (hypothesis): for any shuffled batch of runs per subject, declared order is `as_of`-monotonic per subject and stale rows are skipped.
7. `docs/runbooks/verdict-relay.md` — failure modes and operator actions for the §1.5 monitors (staleness > 26 h, run failure).

### Out of scope
- Computing verdicts or any dbt models — the mart contract is an input (dbt side is warehouse workstream, not this repo)
- The scheduling of relay runs (that's S1.3 — this package exposes the entrypoint only)
- Projection of verdict flags into Twenty (projection consumers are the S2 projection work orders)

### Verification
```
ruff check packages/verdict-relay && pyright packages/verdict-relay
uv run pytest packages/verdict-relay --cov=verdict_relay --cov-fail-under=85 -p no:cacheprovider
uv run pytest packages/verdict-relay/tests/test_ordering.py -q
python -c "import socket" && uv run pytest packages/verdict-relay -q --disable-socket
test -f docs/runbooks/verdict-relay.md
```

### Done means
CI green on PR, coverage ≥ 85% with the property test passing, socket-blocked test run proves no live calls, runbook present. Terminal status: Agent Review.

---

## S1.3 — Build the clock-driven jobs: month-open and reconciliation sweeps

### Context
Package: `packages/schedules`. Depends on: S1.1 (command API client, `open_billing_episode` and `record_communication_consent` command types, idempotency convention). Two jobs, one package, because both are thin clock-driven declarers with identical operational shape. **Month-open:** at month start, open one BillingEpisode per active or on-hold Enrollment (object model §5.2). Reads the enrollment set from the ledger's own current-state read API (S1.1 — confirm endpoint), not from the warehouse, because month-open must not depend on projection freshness. Idempotency makes the job safely re-runnable any day of the month: episodes already open are replays. **D9 reconciliation sweep:** compare ledger CommunicationConsent history against the Customer.io suppression export (CSV, fixture-pinned format on this issue) and declare corrections with actor = `reconciliation`, per object model §5.2. Customer.io wins every conflict — D9. Scheduler mechanism: entrypoints are plain CLIs, invoked by the platform scheduler chosen in D14 (SPCS job / EventBridge Scheduler) — wiring the trigger is infra config in this package's IaC dir, pattern per the monorepo's existing IaC conventions.

### Task
1. `packages/schedules/src/schedules/month_open.py` — enumerate active/on-hold Enrollments from the ledger read API, issue `open_billing_episode` per enrollment × current month with idempotency keys, emit a receipt (opened, replayed, failed) with a hard invariant check: zero enrollments enumerated is a failure, not a success with count 0.
2. `packages/schedules/src/schedules/consent_sweep.py` — parse the suppression export, diff against ledger CommunicationConsent current state, declare corrections (actor = `reconciliation`, provenance = export row ref), emit drift receipt (agreements, corrections, unparseable rows → counted and attached, never dropped).
3. `packages/schedules/src/schedules/cli.py` — one CLI, two subcommands, `--dry-run` on both printing the would-declare set without API calls.
4. `packages/schedules/infra/` — schedule definitions per the monorepo IaC convention: month-open at 00:30 on the 1st with a same-day retry window, sweep daily.
5. `packages/schedules/pyproject.toml` — workspace member.
6. `packages/schedules/tests/fixtures/` — recorded ledger read responses and suppression exports covering: normal month-open, re-run replay, mid-month invocation, zero-enrollment failure case, sweep with corrections in both directions (opt-out missing from ledger, opt-in the export contradicts), malformed export rows. NO live API calls.
7. `docs/runbooks/month-open.md` and `docs/runbooks/consent-sweep.md` — the missed-month-open page procedure (billing incident severity per the ops plan §1.5) and the drift-spike procedure.

### Out of scope
- BillingEpisode qualification verdicts (warehouse computes, S1.2 declares)
- Customer.io API integration for the export pull (v1 consumes a delivered export path — live pull is a follow-on order once the export mechanism is confirmed)
- Genesis backfill runs (genesis has its own work orders per the Genesis and Cutover section)

### Verification
```
ruff check packages/schedules && pyright packages/schedules
uv run pytest packages/schedules --cov=schedules --cov-fail-under=85 --disable-socket
uv run python -m schedules.cli month-open --dry-run --fixture packages/schedules/tests/fixtures/normal_month.json
test -f docs/runbooks/month-open.md && test -f docs/runbooks/consent-sweep.md
```

### Done means
CI green, both jobs fixture-tested including the zero-enrollment and both-direction drift cases, dry-run works offline, runbooks present. Terminal status: Agent Review.

---

## S1.4 — Build the identity resolution service (TIDE matcher v1)

### Context
Package: `packages/identity`. Depends on: S1.1 (command API client, `resolve_referral`, `mint_person`, `attach_identifier` command types), S0.2 (ExternalIdentifier system URI conventions). This service takes a `received` Referral's demographics + source identifiers and either matches an existing Person, mints a new TIDE key, or quarantines as ambiguous — the `received → resolved` transition depends on it from day one of P1, and genesis adjudication reuses it. **v1 is deterministic only:** exact match on (system, value) of any ExternalIdentifier wins outright, else a normalized composite (last name + DOB + sex + first-initial, normalization rules in `matching.md` below) with these outcomes — zero candidates mints, one candidate matches, more than one quarantines. No probabilistic scoring in v1: a wrong auto-merge in a HIPAA system is a reportable event, so ambiguity always goes to a human. Evidence model: every resolution command carries the matched-on fields, the rule id, and candidate set size. Quarantine = the Referral stays in `received` with a `resolution_hold` fact and a row in the review queue table (ledger-side, S1.1 schema — confirm table name), drained by the quarantine reviewer role.

### Task
1. `packages/identity/src/identity/normalize.py` — deterministic normalization: casefold, strip punctuation and suffixes (Jr/Sr/III), DOB parsing with explicit rejection of ambiguous formats, documented in `packages/identity/docs/matching.md` with a table of rules and examples.
2. `packages/identity/src/identity/matcher.py` — the two-tier deterministic match against the ledger's identity read API, returning a typed decision: `Match(person_id, evidence)`, `Mint(evidence)`, `Ambiguous(candidates, evidence)`.
3. `packages/identity/src/identity/resolver.py` — maps decisions to commands: `Match` → `resolve_referral` + `attach_identifier` for any new source identifiers, `Mint` → `mint_person` then resolve, `Ambiguous` → `resolution_hold` fact + queue row. Idempotency keys throughout, evidence attached to every command.
4. `packages/identity/src/identity/service.py` — consumption entrypoint: processes `referral.received` events from the backbone (handler signature per the S1.1 consumer convention — confirm), one referral per invocation, safe under redelivery.
5. `packages/identity/pyproject.toml` — workspace member.
6. `packages/identity/tests/fixtures/` — demographic cases: exact identifier hit, composite unique hit, mint, two-candidate ambiguity, near-miss that must NOT match (same name, different DOB), suffix and casing normalization pairs, ambiguous DOB format rejection. NO live API calls.
7. `packages/identity/tests/test_determinism.py` — property test: resolution of any fixture set is order-independent and re-run-identical (same decisions, same evidence, idempotent commands on replay).
8. `docs/runbooks/identity-quarantine.md` — reviewer procedure: reading evidence, disposition commands, and the merge-by-command path for post-hoc corrections (merge itself is an S1.1 command, referenced not rebuilt).

### Out of scope
- Probabilistic/ML matching (explicitly deferred — register a follow-on when quarantine volume justifies it)
- The review queue UI in Twenty (S2 projection work orders — v1 reviewers work from the queue table + runbook)
- Person merge implementation (`merge_person` is S1.1's command — this package only links to it in the runbook)
- Genesis batch invocation (genesis work orders call this package's matcher — entrypoint stability is the contract, the batch harness is theirs)

### Verification
```
ruff check packages/identity && pyright packages/identity
uv run pytest packages/identity --cov=identity --cov-fail-under=90 --disable-socket
uv run pytest packages/identity/tests/test_determinism.py -q
grep -q "different DOB" packages/identity/tests/fixtures/README.md
test -f packages/identity/docs/matching.md && test -f docs/runbooks/identity-quarantine.md
```

### Done means
CI green, coverage ≥ 90% (identity errs high — wrong matches are the costliest bug in the system), determinism property test passing, the must-not-match case present in fixtures, matching rules and reviewer runbook documented. Terminal status: Agent Review.
