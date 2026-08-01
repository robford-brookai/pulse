# BF-0 — Mongo Archaeology — Dispatch Batch (WORKFLOW v2)

**Purpose:** Execute BF-0 from the backfill plan (`pulse-ledger-backfill-plan.md` v0.4) under the ADE stack. Rewritten from the Open Engine format (v1 of this doc) per WORKFLOW.md v2: BF-0a ships as an OpenSpec change dispatched into Orca, BF-0b runs in the operational-discovery lane outside Orca, BF-0c stays a blocked placeholder. CDC confirmed on the cluster — its coverage window is the central discovery target, setting the E0 ceiling for Enrollment reconstruction.

**Grain map:** Linear parent issue = the `bf0a-archaeology-access` change (BF-0a) and a sibling operational issue for BF-0b. Sub-issues per task per WORKFLOW §1. Statuses are Linear sub-issue statuses (Todo → In Progress → In Review → Done, Blocked with a comment replacing the old HUMAN HOLD token).

**Before dispatch — operator setup (Rob):**
1. G_HARDENING (dispatch-template Appendix A, H1–H4) receipted on a Linear issue — blocks BF-0a's execute step.
2. PULSE repo born from the repo-ade bootstrap (replaces the DNA-695 dependency), `openspec init` and `openlore analyze` done.
3. GitHub App auth: read on `brookai/streamline`, write on the PULSE repo. No PAT.
4. Provision a **read-only** MongoDB Atlas database user for the prod cluster, secret reference in the DuploCloud store (BF-0a defines env var names, BF-0b consumes them). Read-only at the Atlas role level, not by convention.
5. Optional but unblocking for BF-0b: Atlas Admin API key (project read-only) for trigger/CDC enumeration, Snowflake read creds for checking whether CDC already lands in the warehouse. Absent either, BF-0b sets its sub-issue Blocked with the exact console check for Rob.

---

## BF-0a — OpenSpec change `bf0a-archaeology-access`

**Lane:** repo_change. **Dispatch:** `/opsx:propose` → validate (G_MECE) → sync_linear → `task dispatch` → one Orca worktree. **Routing:** `model: opus, max: fable, attempts: 2` — pattern-inheritance work (the STREAMLINE connection pattern must be read correctly), per the rubric's opus row. Single task; `parallel: n/a`.

### Context
Package: `packages/archaeology` (new) in the PULSE monorepo. Depends on: repo-ade bootstrap complete (uv workspace, Taskfile, pre-commit, OpenSpec/OpenLore initialized). Read AGENTS.md first, call `orient("mongo archaeology access package")`, then the change's spec refs. The Mongo connection pattern already exists in `brookai/streamline` — locate it by searching that repo for the client construction (`pymongo`, `motor`, `mongodb+srv`, connection-string assembly) and inherit its shape: driver choice, TLS posture, retry config. Do not invent a new pattern. All auth lives in this repo as *references* — env var names resolving to DuploCloud secret store entries — never literal credentials, never a committed connection string. HIPAA/SOC2 posture throughout.

### Task
1. `packages/archaeology/pyproject.toml` — package metadata per the monorepo template, driver dependency matching streamline's choice.
2. `packages/archaeology/src/archaeology/client.py` — read-only client factory: builds the connection from env vars (match streamline's decomposition), refuses to construct if the resolved user has write roles where detectable, single place all BF-0b access flows through.
3. `packages/archaeology/src/archaeology/smoke.py` — CLI entry (`python -m archaeology.smoke --list-collections`): connects, prints database and collection **names only** (no counts, no contents), exits 0 on success, nonzero with a redacted error otherwise. This is the credentials handshake BF-0b runs first.
4. `packages/archaeology/README.md` — required env vars, the DuploCloud secret entries they resolve to, the read-only role requirement as a hard precondition, and one paragraph: this package exists for backfill archaeology (BF-0) and forward becomes the bulk-extraction seam (mongodump orchestration lands here later, per plan §5 — not now).
5. `packages/archaeology/tests/` — tests first (red-green-refactor), mocked/fixture client, socket-blocking fixture active for the whole suite, zero live network calls. Smoke exercised via argument parsing and error paths only.

### Out of scope
- Extracting or streaming data (BF-0b inspects, Stage 2 orders export in volume)
- Satellite-store connectors — Postgres/MySQL clients for Billy/PAP/ExDash (BF-0c, blocked)
- CDC consumers or forward-sync wiring — Triggers/EventBridge anti-corruption layer is a future change, not archaeology

### Verification
```
task lint && task test
grep -riE "mongodb(\+srv)?://[^\"' ]*@" packages/archaeology --include="*.py" --include="*.toml" --include="*.md" | grep -v "example\|placeholder" ; test $? -eq 1
```

### Done means
Worktree pushed, verification green, HANDOFF.md written (Receipt block, spec deltas or "None"), one commit, no credential material in the tree. Sub-issue → In Review; merged at Phase 8, archived at Phase 9.

---

## BF-0b — Mongo archaeology report (operational-discovery lane)

**Lane:** operational_discovery — a single controlled Claude Code session with scoped runtime creds, **outside Orca** (standing rule per WORKFLOW lanes, independent of G_HARDENING status: prod PHI creds are never ambient in worktrees). Blocked on: BF-0a merged, operator setup 4–5. Receipts and the report attach to the Linear sub-issue. Read backfill plan §3 (evidence classes) and §5 (grain map) first — the report fills that table's "expected ceiling" column. CDC exists: the question is **where it lands, since when, for which collections, with what gaps** — that window is the E0 era.

**PHI hard rules (violation fails the session):**
- Report contains metadata only: collection names, field names, types, presence percentages, document counts, min/max timestamps, storage sizes.
- Never a field *value* from any person-related field — no names, DOBs, MRNs, phone numbers, addresses, free text.
- Sampled documents processed in memory for shape inference and discarded. Nothing lands on disk except the report.
- Report passes the PHI pattern check below before attaching.

### Task
1. Run `python -m archaeology.smoke --list-collections` — paste the exit status (not the output) to the sub-issue as the access receipt.
2. **Inventory:** per database.collection — document count, storage size, min/max of every timestamp-typed field (`created*`, `updated*`, `*_at`, `*Date`). Bounds retention depth per collection in one table.
3. **Journaling census:** per collection, sampled schema shape (field name, BSON type, presence %) with three flag columns: status-like fields (enum-shaped strings named `status`, `state`, `stage`), embedded history (subdocument arrays carrying their own timestamps), and dedicated audit/history collections (`*_history`, `*_audit`, `*_log`, `*events*`) cross-referenced to what they shadow.
4. **CDC trace — the load-bearing section:** mechanism, sink, coverage start, collection coverage, gaps. Evidence paths in order: (a) Atlas Admin API — enumerate Triggers/App Services and event subscriptions (key absent → sub-issue Blocked with the exact console path, continue with b–c); (b) code search across `brookai/streamline` and the PULSE repo for change-stream consumers, Debezium/Kafka config, EventBridge trigger wiring; (c) Snowflake creds present → search for change-event-shaped landing tables (op-type column, cluster time, document payload), report min ingest date. Deliverable: one table — mechanism | sink | start date | collections covered | known gaps — each cell's evidence cited.
5. **Evidence-ceiling table:** plan §5 grains (Enrollment, Referral, Consent, Intervention, Coverage, Device) × era (CDC window vs pre-CDC) → achievable class (E0–E4), one line of justification each. This table prices Stage 2.
6. Summary block: CDC window verdict in one sentence, three most consequential findings, refuted plan-§9 assumptions flagged for Ford (the session does not edit the plan).
7. Attach `bf0b-mongo-archaeology.md` to the sub-issue. Not committed to any repo.

### Out of scope
- Data extraction beyond in-memory shape sampling (Stage 2)
- Satellite stores (BF-0c)
- Remediating findings — a collection with no timestamps gets reported, not fixed
- Editing the backfill plan or object-model doc (Ford's revision pass)

### Verification
```
test -s bf0b-mongo-archaeology.md
grep -q "CDC" bf0b-mongo-archaeology.md && grep -qi "evidence ceiling" bf0b-mongo-archaeology.md
grep -cE "E[0-4]" bf0b-mongo-archaeology.md | awk '{exit ($1>=6)?0:1}'
grep -qiE "\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b|\b(19|20)[0-9]{2}-[01][0-9]-[0-3][0-9]\b.*\b(dob|birth)\b|\b[0-9]{10}\b" bf0b-mongo-archaeology.md ; test $? -eq 1
```

### Done means
Report attached with all five sections, CDC window established with cited evidence (or the specific missing access named on a Blocked sub-issue), evidence ceilings filled for all six grains, PHI check clean. Sub-issue → Done on Ford's review.

---

## BF-0c — Satellite-store archaeology (NOT DISPATCHED — blocked on interview)

Unchanged from v1. Open items: (3) Atlas backup/snapshot posture as an E3 interpolation source, (4) the MySQL holdout's identity and contents, (5) Billy/PAP timestamp and history-table posture, (6) existing historical Snowflake extracts, (7) BHC and Brook+ in or out of evidence scope, (8) satellite prod read access path, (10) ExDash backing store and snapshot cadence. BF-0b's CDC trace may answer (6) for free — hold until that report is in. When unblocked, elaborates as its own operational-discovery session (or an OpenSpec change if connectors get built).

---

## Batch notes

- **Human touchpoints, in order:** receipt G_HARDENING → bootstrap PULSE from repo-ade → provision Mongo read-only creds (+ optional Atlas Admin key, Snowflake read) → Phase 8 merge review of BF-0a → review BF-0b report → answer BF-0c interview items.
- **Why the lanes land this way:** BF-0a is the only diff-producing work, so it is the only Orca work. BF-0b touches prod PHI and produces a report, not a diff — controlled session by rule. The archaeology package deliberately becomes the future bulk-extraction seam so none of this tooling is throwaway.
- **CDC consequence for the plan:** whatever window BF-0b establishes becomes the E0 era for Enrollment. If the sink is Snowflake with deep coverage, Stage 2's priority-2 grain is mostly a dbt exercise over data already in the warehouse — the best possible finding.

## Change log

**v2 (2026-08-01):** Rewritten for WORKFLOW.md v2 — Open Engine mechanics removed (rob-claude titles, agent-instructions label, Agent Todo/Review statuses, HUMAN HOLD tokens), BF-0a recast as OpenSpec change with routing declared, BF-0b recast as operational-discovery session with the standing no-prod-creds-in-Orca rule, DNA-695 dependency superseded by the repo-ade bootstrap, statuses mapped to Linear sub-issues. Task bodies, PHI rules, and verification unchanged.

**v1 (2026-07-31):** Initial batch in Open Engine format.
