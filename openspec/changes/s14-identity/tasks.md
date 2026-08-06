# Tasks — s14-identity

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task; `opus` where a
wrong match or a PHI leak is the retrofit-expensive defect (the normalize and matcher cores).

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket`); the ledger read surface is faked behind the lookup port, the
command API at the `pulse_core` client boundary. Fixtures are synthetic only — no PHI anywhere.
Package coverage floor is **90%** (identity errs high — wrong matches are the costliest bug in
the system).

---

## 1. Wave 0 — scaffold

- [x] 1.1 [DNA-850] Scaffold `packages/identity` as a workspace member: pyproject, uv workspace root entry,
      ruff/pyright/pytest wiring, coverage gate `--cov=identity --cov-fail-under=90`,
      `--disable-socket` posture, `TESTED_PATHS` updated honestly. Test: package imports and an
      empty suite runs green under the gates.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits the root workspace manifest and `Taskfile.yml`.

## 2. Wave 1 — normalization core and fixtures

- [ ] 2.1 `identity/normalize.py` — deterministic normalization and the PHI boundary: casefold,
      punctuation and suffix stripping (Jr/Sr/III), first-initial reduction, DOB parsing with
      explicit rejection of ambiguous formats naming the field (never echoing the value);
      `composite_digest(demographics) -> str` as the only public exit — the readable composite is
      module-internal, held in no dataclass, and transient demographic holders redact in
      `__repr__`/`__str__`. Rules documented as a table with worked examples in
      `packages/identity/docs/matching.md`, versioned v1 (design: a rule change is a breaking
      change to the genesis contract). Tests: suffix/casing variant pairs normalize identically;
      ambiguous DOB rejected naming the field; digest matches `[0-9a-f]{64}`; each documented
      example reproduces the package's actual output.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      Model `opus`: a wrong composite or a composite that escapes the module is the
      retrofit-expensive defect — every registered match key downstream depends on these rules.
- [ ] 2.2 `packages/identity/tests/fixtures/` — synthetic demographic cases: exact identifier
      hit, composite unique hit, mint (unknown everything), two-candidate ambiguity, the
      near-miss that must NOT match (same name, different DOB), suffix and casing normalization
      pairs, ambiguous DOB format. `fixtures/README.md` documents each case by name, including
      the "different DOB" must-not-match case verbatim (verification greps for it). Test: a
      loader validates fixture shape; no live network anywhere.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 3. Wave 2 — matcher core

- [ ] 3.1 `identity/matcher.py` — the two-tier deterministic match: candidate-lookup port
      (`Protocol`) with an in-memory test adapter; exact `(system, value)` tier short-circuits;
      composite tier decides by candidate count alone — zero → `Mint`, one → `Match`, >1 →
      `Ambiguous`; frozen decision dataclasses (`Match(person_id, evidence)`, `Mint(evidence)`,
      `Ambiguous(candidates, evidence)`) and `Evidence(matched_fields, rule_id, candidate_count)`
      carrying field *names*, never values; stable rule ids (`identifier_exact`,
      `composite_unique`, `composite_none`, `composite_ambiguous`). No scoring, no thresholds, no
      tie-breaking — deterministic only. Tests (fixtures from 2.2): exact hit short-circuits past
      a would-be composite match; zero/one/two trichotomy; near-miss same-name-different-DOB
      mints; every decision's evidence names fields, rule id, and candidate count.
      `[model: opus | deps: 2.1, 2.2 | lane: repo_change | wave: 2]`
      Model `opus`: a wrong match here is the reportable event the whole v1 posture exists to
      prevent.
- [ ] 3.2 `identity/lookup.py` — live lookup adapter over the ledger read surface: wraps
      `pulse_ledger.identity.lookup_identifier(conn, system=..., value=...)` and
      `pulse_ledger.identity.find_candidates(conn, match_key)`, conforming to the 3.1 port.
      Tests: the adapter transmits only the sha256 digest for the composite tier (readable
      composite absent from every call); port conformance against the in-memory adapter's
      contract suite.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 2]`

## 4. Wave 3 — resolver and service

- [ ] 4.1 `identity/resolver.py` — decisions to commands: `Match` → `resolve_referral` +
      `attach_identifier` only for identifiers the person does not already hold; `Mint` →
      `mint_person` → `resolve_referral` → attach, in that order; D16 idempotency keys derived
      per logical resolution (triggering `event_id` as logical time) via
      `pulse_core.idempotency.derive_idempotency_key`; the decision's evidence attached to every
      command; `rejected` stops the sequence and routes to quarantine with the rejection in
      evidence, `transient` retries via the client. Tests: match-with-new-identifier declares
      both commands with evidence; mint ordering; already-held identifiers skipped; identical
      resolution replayed yields no new events (all at the faked `pulse_core` client boundary);
      caplog scan across the resolver's decision/evidence logging (flagged path (c) in design
      decision 3) finds no fixture demographic string.
      `[model: sonnet | deps: 3.1 | lane: repo_change | wave: 3]`
- [ ] 4.2 Quarantine path: `Ambiguous` → `resolution_hold` fact (no `to_state`; subject stays
      `received`) + `pulse_ledger.review.quarantine_subject` queue row holding pseudonymous
      person keys only — no demographic field enters the queue; both effects idempotent so a
      crash between them converges on redelivery. Tests: two-candidate case leaves the Referral
      in `received` with a hold fact and a queue row carrying exactly the two person keys and no
      demographics; reprocessing a pending referral does not double-enqueue.
      `[model: sonnet | deps: 4.1 | lane: repo_change | wave: 3]`
- [ ] 4.3 `identity/service.py` — consumption entrypoint via
      `pulse_core.client.consume(handler, queue_url=...)` (`ConsumerHandler` signature): one
      referral per invocation, `event_id` dedupe, delete only after the handler returns. This is
      the composition root: the handler wires the 3.2 live adapter into the 3.1 matcher and the
      4.1/4.2 resolver as the runnable production entrypoint. The two flagged logging paths
      hardened per design decision 3 — handler failures log `event_id` + subject key, never the
      envelope; rejections name fields, never values. Tests: crash-before-delete redelivery
      converges to the single-clean-run ledger state; caplog scan across every failure path,
      driven through the full service → matcher → resolver stack, finds no fixture demographic
      string.
      `[model: sonnet | deps: 3.2, 4.1, 4.2 | lane: repo_change | wave: 3]`

## 5. Wave 4 — proof and documentation

- [ ] 5.1 `packages/identity/tests/test_determinism.py` — the property test: resolution of any
      fixture set is order-independent and re-run-identical (same decisions, same evidence,
      idempotent commands on replay), driven through the library entrypoint directly — no queue,
      no service process — proving the genesis batch-invocation contract yields the same typed
      decisions the service path produces.
      `[model: sonnet | deps: 3.1, 4.1 | lane: repo_change | wave: 4]`
- [ ] 5.2 `docs/runbooks/identity-quarantine.md` + the published contract: runbook covers reading
      an evidence record from the queue row's pseudonymous keys, the disposition commands per
      outcome, and the merge-by-command correction path (`merge_person` is S1.1's command —
      linked, not rebuilt); register the matcher entrypoint, decision types, and rule ids in
      `docs/contracts/publishes.md` (genesis calls it; entrypoint stability is the contract).
      Tests: `mkdocs build -s` green; verification file-existence checks pass.
      `[model: sonnet | deps: 4.2, 5.1 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater lane, contract and spec-adjacent files.
- [ ] 5.3 Verification wrap — the work order's block, end to end on a fresh checkout:
      `ruff check packages/identity && pyright packages/identity`;
      `uv run pytest packages/identity --cov=identity --cov-fail-under=90 --disable-socket`;
      `uv run pytest packages/identity/tests/test_determinism.py -q`;
      `grep -q "different DOB" packages/identity/tests/fixtures/README.md`;
      `test -f packages/identity/docs/matching.md && test -f docs/runbooks/identity-quarantine.md`.
      Test: the block itself, plus `task check` green — any failure is fixed here before Agent
      Review.
      `[model: sonnet | deps: 5.1, 5.2 | lane: repo_change | wave: 4]`
