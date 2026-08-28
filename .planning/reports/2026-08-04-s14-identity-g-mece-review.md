# G_MECE validation — s14-identity

Reviewer: worker task_756efc460fb6. Read-only review; `openspec validate s14-identity --strict`
plus manual cross-check against `design/delivery/pulse-s1-work-orders.md` §S1.4 and
`packages/pulse-ledger/src/pulse_ledger/{identity,review}.py`. No writes made.

## 0. `openspec validate --strict`

**PASS** — `Change 's14-identity' is valid`.

## 1. Per-check G_MECE verdicts

### every_requirement_has_scenario — PASS
All 14 requirements across the three spec files carry ≥1 scenario:
- `identity-normalization/spec.md`: 3 requirements (lines 9, 31, 43), 5 scenarios.
- `identity-matching/spec.md`: 6 requirements (lines 9, 24, 51, 64, 76, 89), 8 scenarios.
- `identity-resolution/spec.md`: 5 requirements (lines 9, 23, 36, 57, 69, 84 — note the runbook
  requirement at line 84 has no `### Requirement:` heading issue; all requirement headers
  present), 8 scenarios.

### task_scenario_bijection_covered — PASS, one soft gap noted
Every scenario maps to a task:
- normalize scenarios → 2.1 (tasks.md:28-40)
- "only digest reaches ledger" → 3.2's adapter test (tasks.md:64-70, "adapter transmits only the
  sha256 digest for the composite tier")
- matcher scenarios → 3.1 (tasks.md:51-63)
- entrypoint-stability scenario → 5.1 (tasks.md:102-107)
- resolver/mint/quarantine/redelivery scenarios → 4.1/4.2/4.3 (tasks.md:74-98)
- runbook scenario → 5.2 (tasks.md:108-115)

**Soft gap:** design.md decision 3 (design.md:68-78) commits to testing all three flagged
PHI-to-logger paths via "caplog scan for fixture demographic strings across every failure path."
Only task 4.3 (tasks.md:91-98) states an explicit caplog-scan test, scoped to `service.py`'s
failure paths. Flagged path (c) — "decision/evidence logging in `resolver.py`" — has no task
(4.1, tasks.md:74-83; 4.2, tasks.md:84-90) stating an equivalent caplog assertion; 4.1/4.2's test
lists check command/queue-row *content* (no demographics in the queue row) but not log output. If
4.3's caplog scan only exercises `service.py`'s own log calls rather than the full
service→resolver call stack, the design's "tests assert all three" claim is not fully bijected
into tasks. Not necessarily a defect — plausibly covered if 4.3's test drives the full pipeline —
but the task text doesn't say so explicitly. Confidence: moderate.

### tasks_atomic_2h — PASS
No task's scope reads as exceeding ~2h for its stated model tier. Task 2.1 and 3.1 are the
densest (normalization rule set + doc table + 4 test scenarios; two-tier matcher + port + 5 test
scenarios) but each is a single cohesive file + its tests, matching this repo's established
task-granularity convention (one module per task) and both are already flagged `opus` for
retrofit-expensive-defect reasoning (design.md:38-40, 61-63), which is consistent with them being
the largest units in the set, not evidence of non-atomicity.

### no_scope_overlap — PASS, one documentation gap noted
File ownership by task: 1.1 workspace root + Taskfile; 2.1 `normalize.py`; 2.2
`tests/fixtures/`; 3.1 `matcher.py`; 4.1/4.2 `resolver.py` (4.2 depends on 4.1, so no parallel
write conflict); 4.3 `service.py`; 5.1 `tests/test_determinism.py`; 5.2 runbook +
`docs/contracts/publishes.md`. No two tasks without a dependency edge between them claim the same
file.

**Gap:** task 3.2 (tasks.md:64-70, "Live lookup adapter over the ledger read surface") is the only
task in the file that does not name its target module path (every other task opens with an
explicit file path). It depends on 3.1 (`matcher.py`) so there's no parallel-write risk given the
dep ordering, but the missing path leaves it ambiguous whether the live adapter lives inside
`matcher.py` (extending 3.1's file) or a new module — worth naming explicitly before dispatch.

### deps_explicit — PASS with one real finding
All tasks state a `deps:` field (or `—`). One dependency appears to be missing:

**Finding:** task 4.3 (`identity/service.py`, tasks.md:91-98) declares `deps: 4.1, 4.2` only — it
does not depend on 3.2 (tasks.md:64-70, the live lookup adapter over
`pulse_ledger.identity.lookup_identifier`/`find_candidates`). Per `scripts/dispatch_tasks.py`
`releasable()`, a task releases as soon as every *declared* dependency is checked off — there is
no implicit wave-completion barrier (confirmed by reading `releasable()` directly: "A task
releases when every task it depends on is checked off"). If `service.py`'s consumption handler is
what composes the pure decision core with the live adapter for production use (the only place in
this task list where that composition would happen — design.md decision 1 says the effectful
shell owns command submission and consumption, and decision 4 introduces the live adapter as what
"the live path" wraps), then 4.3 could be dispatched and completed while 3.2 is still pending,
leaving `service.py` with no live adapter to wire against, or duplicating adapter code. If the
production wiring instead happens somewhere the task list doesn't cover (a composition root not
enumerated in tasks.md), that's a separate gap — no task explicitly assembles
matcher+live-adapter+resolver+service into a runnable production entrypoint. Either reading is a
finding worth resolving before dispatch.

### deps_reference_existing_tasks — PASS
Every `deps:` value (1.1, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.3, 5.1, 5.2) resolves to a task number
that exists in this file. No dangling references. Declared wave labels are also internally
consistent with the dependency graph (no dep whose wave rank exceeds its dependent's wave — checked
by hand against `_wave_rank` semantics in `scripts/dispatch_tasks.py:347-358`).

### model_declared_or_default — PASS
Every task states `model:` explicitly (no implicit defaults relied on): sonnet — 1.1, 2.2, 3.2,
4.1, 4.2, 4.3, 5.1, 5.2, 5.3; opus — 2.1, 3.1, each with an explicit rationale sentence
(tasks.md:38-40, 61-63) matching the "wrong composite/match is the retrofit-expensive defect"
criterion from the file's header convention (tasks.md:6-7).

### serial_flags_justified — PASS
Two serial flags, both justified:
- 1.1 `serial: workspace_roots` — "edits the root workspace manifest and `Taskfile.yml`"
  (tasks.md:24).
- 5.2 `serial: openspec_main_specs` — "doc-updater lane, contract and spec-adjacent files"
  (tasks.md:115).

## 2. PHI extra bar

- **Ledger never receives demographics**: intact end to end. Spec (`identity-normalization/spec.md:43-55`),
  design (design.md:15-18, 68-78), and proposal (proposal.md:34-37) all state the invariant
  identically, and the actual ledger code enforces it structurally —
  `packages/pulse-ledger/src/pulse_ledger/identity.py:36-37,58-65,171-186` (`MATCH_KEY_PATTERN`,
  `MalformedMatchKeyError`, `register_match_key`/`find_candidates` reject any non-`[0-9a-f]{64}`
  argument). Task 3.2's test explicitly asserts the composite tier transmits only the digest
  (tasks.md:67-68). **Confirmed.**
- **Evidence carries field names, never values**: design decision 2 (design.md:60-67) and the
  matching spec's "Evidence names fields, rule, and candidate count" scenario
  (`identity-matching/spec.md:64-74`) both state this; task 3.1's evidence dataclass and tests
  enforce it (tasks.md:55-60). **Confirmed.**
- **PHI-to-logger paths flagged with tests**: design decision 3 names three flagged paths
  (design.md:73-78) and commits to testing all three via caplog scan. Only one task (4.3) states
  an explicit caplog-scan test; see the soft gap under `task_scenario_bijection_covered` above —
  **plausible but not conclusively covered for the resolver.py path.**
- **All fixture examples synthetic**: stated repeatedly (proposal.md's Impact section calls out
  "Fixtures are synthetic only — no PHI anywhere," tasks.md:11, task 2.2's fixture list at
  tasks.md:41-47 is demographic *cases* by shape, not real data). No literal PHI-shaped values
  appear in any of the four artifact files reviewed. **Confirmed**, contingent on the fixtures
  themselves (not yet written) actually staying synthetic — nothing in the plan risks this.

## 3. Cross-check against `pulse-s1-work-orders.md` §S1.4 and cited code

- Proposal, design, and tasks all match §S1.4's Context/Task/Verification text closely — package
  name, file list, command types, coverage floor (90%), verification block (`ruff`, `pyright`,
  pytest with `--cov-fail-under=90 --disable-socket`, determinism test, fixture grep, doc
  file-existence checks) all agree verbatim or near-verbatim.
- Every cited `pulse_ledger`/`pulse_core` surface exists with the signature claimed:
  - `pulse_ledger.identity.lookup_identifier(conn, *, system, value)` —
    `packages/pulse-ledger/src/pulse_ledger/identity.py:153-159`. Matches.
  - `pulse_ledger.identity.find_candidates(conn, match_key)` — same file, lines 189-205. Matches
    (raises `MalformedMatchKeyError` for non-digest input, as design.md:79-84 assumes).
  - `pulse_ledger.review.quarantine_subject(conn, *, subject_type, subject_key, hold_event_id,
    candidates)` — `packages/pulse-ledger/src/pulse_ledger/review.py:131-173`. Matches, including
    the "pending at most once" guarantee (`SubjectAlreadyPendingError`, review.py:68-76,166-170)
    the design leans on (design.md:93-97).
  - `pulse_core.client.consume(handler, queue_url=...)`, `ConsumerHandler =
    Callable[[Mapping[str, object]], None]` — `packages/pulse-core/src/pulse_core/client.py:330,436`.
    Matches.
  - `pulse_core.idempotency.derive_idempotency_key` —
    `packages/pulse-core/src/pulse_core/idempotency.py:83`. Matches.
  - Command types `resolve_referral`, `mint_person`, `attach_identifier` — all present in
    `packages/pulse-core/src/pulse_core/generated/__init__.py:77,82,86,110,156,183`. Matches.
  - `resolution_hold` (no `to_state`) — corroborated by
    `packages/pulse-ledger/src/pulse_ledger/commit.py:135,377` ("A declaration with no `to_state`
    (`resolution_hold`, ...) is not a transition"). Matches the design's claim
    (design.md:19-20).
- No discrepancy found between the change's claims and the cited code or work order.

## Overall verdict

**PASS**, with two findings worth resolving before dispatch (both under `deps_explicit` /
`no_scope_overlap`, neither a spec/scenario defect):

1. Task 4.3 does not declare a dependency on 3.2 (the live lookup adapter), and no task explicitly
   composes matcher + live adapter + resolver into a runnable production entrypoint — confirm
   whether 4.3 needs `deps: 3.2` added, or whether composition happens elsewhere.
2. Task 3.2 doesn't name its target file path (every sibling task does) — clarify whether it
   extends `matcher.py` or introduces a new module.

Plus one moderate-confidence PHI-bar soft gap: design decision 3's "tests assert all three [flagged
logging paths]" claim is only explicitly tasked for one of the three (service.py); confirm 4.3's
caplog scan actually exercises the resolver.py call path, or add an explicit assertion to
4.1/4.2.
