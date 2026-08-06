# Proposal — s14-identity

## Why

The `received → resolved` Referral transition has no resolver: nothing today takes a received
Referral's demographics and source identifiers and decides which Person it is. S1.1
(`pulse-ledger-core`, archived 2026-08-03) shipped every surface this service consumes — the
command API client, the `resolve_referral` / `mint_person` / `attach_identifier` command types,
the identity read surface (`external_identifiers`, `person_match_keys`), and the quarantine
review queue — so S1.4 is unblocked and gate-free per the Phase 2 ladder. Genesis adjudication
(BF-x) reuses this same matcher, so its entrypoint is a published contract from day one.

## What Changes

- **New package `packages/identity`** (workspace member): the TIDE matcher v1 and its resolution
  service.
- **Deterministic normalization** (`identity/normalize.py`): casefold, punctuation and suffix
  stripping (Jr/Sr/III), DOB parsing with explicit rejection of ambiguous formats — rules
  documented as a table with examples in `packages/identity/docs/matching.md`.
- **Two-tier deterministic matcher** (`identity/matcher.py`): exact `(system, value)`
  ExternalIdentifier match wins outright; else the normalized composite
  (last name + DOB + sex + first-initial) — zero candidates mints, one matches, more than one
  quarantines. **v1 is deterministic only** — no probabilistic scoring: a wrong auto-merge in a
  HIPAA system is a reportable event, so ambiguity always goes to a human. Typed decisions:
  `Match(person_id, evidence)`, `Mint(evidence)`, `Ambiguous(candidates, evidence)`.
- **Resolver** (`identity/resolver.py`): decisions → commands. `Match` → `resolve_referral` +
  `attach_identifier` for new source identifiers; `Mint` → `mint_person` then resolve;
  `Ambiguous` → `resolution_hold` fact + `ledger.review_queue` row via
  `pulse_ledger.review.quarantine_subject`. D16 idempotency keys throughout; every resolution
  command carries evidence (matched-on fields, rule id, candidate set size).
- **Consumption entrypoint** (`identity/service.py`): processes `referral.received` events via
  `pulse_core.client.consume(handler, queue_url=...)` — one referral per invocation, safe under
  redelivery.
- **PHI containment**: the ledger never receives demographics. The normalized composite is PHI;
  the ledger stores only its sha256 digest (`ledger.person_match_keys`, `[0-9a-f]{64}` check
  constraint). Normalization and hashing live in this package only; review-queue candidate sets
  hold pseudonymous person keys only.
- **Reviewer runbook** `docs/runbooks/identity-quarantine.md`: reading evidence, disposition
  commands, and the merge-by-command path (`merge_person` is S1.1's command, referenced not
  rebuilt).
- **Published contract**: the matcher entrypoint is registered in `docs/contracts/publishes.md` —
  genesis's batch harness calls it; entrypoint stability is the contract.

## Capabilities

### New Capabilities

- `identity-normalization`: deterministic demographic normalization — the rules that produce the
  composite match key, ambiguous-input rejection, and the PHI boundary (readable composite never
  leaves the package; only its sha256 digest reaches the ledger).
- `identity-matching`: the two-tier deterministic match — exact identifier tier, composite tier,
  the mint/match/quarantine trichotomy, the evidence model, determinism guarantees, and
  entrypoint stability for genesis.
- `identity-resolution`: decision-to-command mapping, quarantine mechanics
  (`resolution_hold` + review queue), event consumption, and idempotency under redelivery.

### Modified Capabilities

_None. `ledger-read` (identifier lookup, candidate retrieval, review queue) and `command-api`
(idempotency, attribution) are consumed as shipped by S1.1; no requirement of theirs changes._

## Impact

- New package under `packages/` following the workspace conventions (uv, ruff, pyright, pytest);
  coverage floor **90%** for this package — higher than siblings, because wrong matches are the
  costliest bug in the system.
- Consumes S1.1 surfaces: `pulse_core.client.PulseCoreClient` / `consume`,
  `pulse_core.idempotency.derive_idempotency_key`, `pulse_ledger.identity.lookup_identifier` /
  `find_candidates`, `pulse_ledger.review.quarantine_subject`. Consumes S0.2 ExternalIdentifier
  system URI conventions.
- Publishes: the matcher entrypoint (genesis contract) → `docs/contracts/publishes.md`.
- Not affected: the `idempotency_key`/`replayed` HTTP gap (DNA-801) blocks only S1.2's declarer;
  this service's correctness does not depend on replay classification.
- Out of scope (deferred, not dropped): probabilistic/ML matching (register a follow-on when
  quarantine volume justifies it), the Twenty review-queue UI (S2 projection work), person merge
  implementation (S1.1's `merge_person`), genesis batch invocation (their harness, our
  entrypoint).
- Rollback: pre-production, no live writers until the C1 BAA gate clears — reverting is deleting
  the package; no data migration exists.
