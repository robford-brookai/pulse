# Design — s14-identity

## Context

See proposal.md — Why. Constraints that shape the design:

- Every consumed surface is pinned, not to-confirm (S1.1 task 5.2 / DNA-799):
  `pulse_core.client.PulseCoreClient.submit_command` classifying
  `committed | replayed | rejected | transient`, `pulse_core.client.consume(handler, queue_url=...)`
  with `ConsumerHandler = Callable[[Mapping[str, object]], None]`,
  `pulse_core.idempotency.derive_idempotency_key` (D16),
  `pulse_ledger.identity.lookup_identifier(conn, system=..., value=...)`,
  `pulse_ledger.identity.find_candidates(conn, match_key)`,
  `pulse_ledger.review.quarantine_subject` (pending at most once).
- `ledger.person_match_keys` stores sha256 digests only, enforced by a `[0-9a-f]{64}` check
  constraint; `register_match_key` refuses anything else. The readable composite (last name +
  DOB + sex + first-initial) is PHI and exists only inside this package — by ledger construction,
  not by convention.
- `resolution_hold` is committable with no `to_state` (S1.1 task 3.5): the write path skips
  transition validation and the state re-fold, so a quarantined Referral stays in `received`.
- Genesis adjudication (BF-x) calls this matcher in batch; the entrypoint is a published contract
  (`docs/contracts/publishes.md`), so the decision API must not assume a queue or a live service.
- **v1 is deterministic only.** Exact `(system, value)` identifier match wins outright; else the
  normalized composite decides by candidate count — zero mints, one matches, more than one
  quarantines. No probabilistic scoring: a wrong auto-merge in a HIPAA system is a reportable
  event, so ambiguity always goes to a human.
- Auth per D15: credential names in config, values from the environment, never in code or
  fixtures. No live network in any test (`--disable-socket`).

## Goals / Non-Goals

**Goals:**

- One pure decision core (normalize → match → typed decision) that the service path and genesis's
  batch harness share unchanged.
- PHI containment that is structurally checkable: the readable composite has exactly one module
  boundary it cannot cross, and tests assert it never crosses.
- Every decision reconstructable by a human from its evidence alone — matched-on fields, rule id,
  candidate set size.

**Non-Goals:**

- No probabilistic/ML matching (follow-on when quarantine volume justifies it), no review-queue
  UI (S2), no `merge_person` implementation (S1.1's command, runbook links only), no genesis
  batch harness (theirs; our contract is entrypoint stability).
- No caching or read-replica strategy: matcher reads go to the ledger's identity read surface at
  PRM volume; optimizing reads before there is volume is speculation.

## Decisions

1. **Layering: pure core, effectful shell.** `normalize.py` and `matcher.py` are pure — no ledger
   writes, no queue, no clock: demographics + a candidate-lookup port in, a frozen decision out.
   `resolver.py` owns all command submission; `service.py` owns consumption. This is what makes
   the determinism property test cheap (shuffle inputs, re-run, compare decisions with no
   mocking of effects) and what makes the genesis contract a function import rather than a
   service dependency.
   *Alternative rejected:* matcher calls the ledger and declares commands directly — collapses
   the layers genesis needs separated and makes order-independence untestable without a fake
   ledger in every property run.
2. **Typed decisions as frozen dataclasses:** `Match(person_id, evidence)`, `Mint(evidence)`,
   `Ambiguous(candidates, evidence)`; `Evidence(matched_fields, rule_id, candidate_count)`.
   Rule ids are stable strings (`identifier_exact`, `composite_unique`, `composite_none`,
   `composite_ambiguous`) — they appear in evidence records, review-queue triage, and the
   runbook, so they are part of the published contract alongside the entrypoint signature.
   `Evidence.matched_fields` holds field *names* (e.g. `("last_name", "dob", "sex",
   "first_initial")`), never field values — evidence travels in command payloads to the ledger,
   and values would re-import the PHI the digest design just removed.
3. **The PHI boundary is one function.** `normalize.py` exposes `composite_digest(demographics) ->
   str` (sha256 hex) as the only thing callers get; the readable composite is an internal of that
   module, built and hashed in one place, held in no dataclass, returned from no public function.
   `__repr__`/`__str__` on any type that transiently holds demographics (the parsed referral
   input) is overridden to redact. **Flagged code paths where the readable composite or raw
   demographics could reach a logger:** (a) the service handler's exception path — a naive
   `logger.exception` on a handler failure would serialize the envelope, which carries referral
   demographics; the handler logs `event_id` + subject key only; (b) DOB-rejection errors — the
   rejection names the *field*, never echoes the offending value; (c) decision/evidence logging in
   `resolver.py` — safe by construction only because evidence holds field names, per decision 2.
   Tests assert all three (caplog scan for fixture demographic strings across every failure path).
4. **Candidate lookup is a port (`Protocol`) with two adapters:** the live adapter wraps
   `pulse_ledger.identity.lookup_identifier` / `find_candidates`; the test adapter is an
   in-memory dict. Genesis brings its own adapter if it batches reads. The port is part of the
   entrypoint contract; the live adapter is not.
   *Alternative rejected:* patching `pulse_ledger` in tests — couples every test to the ledger
   package's internals and hides the contract genesis programs against.
5. **Resolver command order and idempotency:** `Mint` declares `mint_person` → `resolve_referral`
   → `attach_identifier`(s); `Match` declares `resolve_referral` → `attach_identifier` for
   identifiers the person lacks (present ones are skipped, not re-attached — attaching an
   identifier held by another person would be rejected naming the holder, and that rejection is
   quarantine-worthy, not retryable). Idempotency keys derive per D16 from the logical resolution
   (subject, command type, payload, logical time = the triggering `event_id`), so redelivery
   replays rather than duplicates. A `rejected` response on any step stops the sequence and
   quarantines with the rejection in evidence; `transient` retries via the client's backoff.
6. **Quarantine is two effects, made convergent by construction:** the `resolution_hold` fact
   (idempotent by D16 key) and `quarantine_subject` (pending at most once, per S1.1). Either may
   have happened before a crash; both are safe to repeat, so the handler needs no distributed
   transaction. Queue rows carry pseudonymous person keys only; the reviewer reaches evidence
   through this service's evidence record, per the runbook.
7. **Coverage floor 90** (`--cov=identity --cov-fail-under=90`), higher than the sibling
   packages: identity errs high because wrong matches are the costliest bug in the system —
   a wrong auto-merge is a reportable event, and the marginal cost of covering branch paths in a
   pure decision core is low.

## Risks / Trade-offs

- **Deterministic-only inflates quarantine volume** (nicknames, transposed DOB digits, hyphenated
  surnames all mint or quarantine rather than fuzzy-match) → accepted deliberately: the failure
  mode is human workload, never a wrong merge. Quarantine volume is the named trigger for the
  probabilistic follow-on; the runbook drains the queue meanwhile.
- **Normalization rules are a compatibility surface**: changing a rule changes composites, hence
  digests, hence candidate sets — existing `person_match_keys` rows were registered under the old
  rules → rules are versioned in `matching.md` from v1, and any rule change is a breaking change
  to the genesis contract requiring a re-registration plan, not a patch.
- **Two-effect quarantine is not atomic** (hold fact and queue row commit separately) → both
  idempotent, handler-crash redelivery converges; the review queue's pending-at-most-once
  invariant absorbs the replay.
- **PHI in the consumed envelope**: `referral.received` events carry demographics into the
  handler, so the package processes PHI even though it stores none → flagged logging paths in
  decision 3 are each tested; security review on any PR touching `service.py` or logging config,
  per the repo PHI rules. Fixtures are synthetic only.
- **`event_id` as logical time makes redelivery a replay but a re-*send* of the same referral a
  new resolution** (new event, new keys) → correct: a genuinely re-sent referral re-resolves
  against the current identifier/match-key state, and idempotent outcomes (already resolved,
  already pending) are replays or rejections the resolver already classifies.
