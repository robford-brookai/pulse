# Design: billing-source-boundary

## Context

Inputs this design is built from, each verified against the repo or the named external source
on 2026-08-21:

- **The engine exists and is complete, in `robford-brookai/cpt-om`.** Its single source of
  truth, `cpt_model/cpt-model.json`, holds 34 CPT codes, 19 standard rates, 19 partner rate
  cards, code ladders, code groups, prerequisites, and four regulatory gates (`D2_apcm`,
  `D4_99091_concurrency`, `D7_rtm`, `D8_bhi_cocm`), with two compilers off the one model (an
  HTML decision-tree artifact and a MILP optimizer rationing nurse-minutes against captured
  reimbursement) and a conformance test as its drift guard. It references PULSE nowhere.
- **PULSE's billing machinery is verdict-shaped and amount-free already.** `billing_episode`
  carries counters (`accrued_minutes`, `reading_days`), states, stamps, and `rule_version` —
  no monetary field. `billing-state` (in flight, 9/10 tasks done) shipped the
  verdict→transition pairing in the relay (`transition_by_outcome`, its design decision 3) and
  left exactly one seam open: its open question 3, which of two sanctioned ways the pricing
  engine connects.
- **The envelope already refuses what this change forbids.** `pulse_ledger.api` raises
  `UnknownDeclarationFieldError` for any body field a declaration has no place for — "refused,
  never silently dropped" — so a top-level monetary field on a command is already structurally
  impossible. What is missing is the *stated guarantee* and the tests that pin it, not code.
- **The boundary rule is standing policy** (Rob, 2026-08-19, recorded in `billing-state`
  design): apps cross the pulse line through connectors only — in via the command API under
  the connector's own credential, out via the bus or published surfaces. No point-to-point.
- **The governed producer list does not exist.** The sanctioned command sources are prose in
  `design/migration/ocean-to-pulse-adaptation-plan.md` (§ "Sanctioned command sources"): the
  Twenty kanban webhook (D8), Customer.io consent ingress (D9), the identity-resolution
  service, the warehouse verdict runner (I3), and human actors through attributed tooling.
  The "~11 surfaces" list (`packages/ocean/docs/pt-data-infra-acq-status.md`) is a legacy
  problem inventory, not a contract.

## Decisions

### 1. cpt-om declares directly through the command API — answers billing-state open question 3

**Decided 2026-08-21. Gates: the cpt-om registry entry's seam column, and any future
`billing-eligibility-ingress` change.**

The two options billing-state left open, both boundary-legal:

- **(a) Mart-feed:** cpt-om writes its qualification results into the Snowflake mart the
  verdict relay already polls; the relay declares on its behalf.
- **(b) Direct-declare — chosen:** cpt-om declares `billing_eligibility` verdicts through the
  command API under its own credential, the `customerio-consent-ingress` precedent
  (ADR-0005).

Why (b):

- **Attribution is authentication (D15).** Under (a) every cpt-om verdict is attributed to the
  relay's actor, and the deciding system disappears from the event record; `rule_version` and
  `lineage_ref` would be laundered through a mart written by someone else. Under (b) the
  ledger sees the decider as the actor, which is the entire point of D15.
- **(a) creates the cross-repo seam billing-state's decision 6 already rejected.** The mart
  feed would make cpt-om a producer into the dbt/Snowflake estate — a seam
  `docs/contracts/consumes.md` says has no publisher contract owner yet. Direct-declare needs
  no third party.
- **Freshness decouples from the poll.** Under (a), declare-back lag is dbt refresh + relay
  poll interval on top of cpt-om's own run cadence. Under (b), it is cpt-om's cadence alone.
- **The registry stays honest.** Under (a) the registry would have to name the mart as the
  producer and footnote cpt-om, or vice versa; under (b) one row states the truth.

*What this does not decide:* the relay's mart path stays exactly as billing-state shipped it,
for verdicts computed in the warehouse (`rule_domain` separation per the state-catalog rule).
Direct-declare is the seam for *external deciding systems*; the mart is the seam for
*warehouse-computed* verdicts. Both are registry rows.

### 2. The registry is a markdown table in `docs/contracts/`, guarded by a repo-level test

**Decided 2026-08-21. Gates: tasks 1.1 and 2.1 of this change.**

`docs/contracts/` is already the cross-repo integration surface (`publishes.md`,
`consumes.md`), so the registry lands there as `producer-registry.md`: one table row per
system, columns exactly `System | Direction | Seam | Credential / actor | Grain | Status |
Notes`, status from the fixed vocabulary `shipped | spec-only | planned | blocked |
excluded-by-design`. A repo-level test parses the table and enforces the shape — the same
pattern as `tests/test_producer_ingress_policy.py`, which the proposal names as this rule's
analogue.

*Alternative rejected — YAML registry with a generated page.* The catalog doctrine (one
generative artifact, emitted surfaces) is right for surfaces with multiple consumers, but the
registry has exactly one consumer: a human integrator reading a contract. A YAML + generator
pair would add a build step and a drift axis to protect against a problem (hand-edited
divergence between two renderings) that a single hand-edited table cannot have. If a tool ever
needs to read the registry, the parsing test already proves the table is machine-readable.

### 3. The amount-free guarantee is pinned by tests, not new validation code

**Decided 2026-08-21. Gates: tasks 2.1 and 2.2.**

Three layers, each with an explicit, offline assertion:

- **Catalog:** no subject field in `catalog/state_catalog.yaml` may match the monetary
  deny-list (`rate`, `amount`, `price`, `revenue`, `copay`, `fee`, `charge`, `cost`, `cpt`,
  `hcpcs`, `usd`, `cents`, `dollars` — as substrings of field names, case-insensitive). The
  deny-list lives in the test, spelled out, so a reviewer sees exactly what is forbidden.
- **Command envelope:** a declaration body carrying a top-level monetary field (e.g.
  `allowed_amount`) is refused via `UnknownDeclarationFieldError` — asserted by test against
  the real `pulse_ledger.api` coercion path, proving refusal rather than silent drop.
- **Evidence stays open:** the same test module proves the complement — a verdict whose
  `payload` carries a copay figure commits cleanly, because payload and `lineage_ref` are
  opaque evidence (billing-state decision 2). The boundary is between state and evidence, not
  a keyword ban on the whole body.

No production code changes. If a future command schema ever adds typed payload fields, the
catalog deny-list test is the tripwire that forces the boundary conversation then.

### 4. Requirement "qualification recorded as verdict + rule_version" is satisfied by
billing-state — recorded, not re-implemented

**Decided 2026-08-21. Gates: the task↔scenario bijection in tasks.md.**

The `billing-computation-boundary` delta's second requirement (verdict moves state with
provenance; nothing downstream recomputes) is exactly what billing-state's relay pairing
shipped: `transition_by_outcome` for `billing_eligibility`, D16-keyed pair replay, tests in
`packages/verdict-relay/tests/` (`test_declarer.py`, `test_run.py`). This change adds **no
task and no test** for those two scenarios; the bijection map in tasks.md cites the existing
coverage by file. Writing parallel tests here would create the same-wave scope overlap G_MECE
exists to prevent, against a change that is still in flight.

## Open questions

1. **`Contract.terms.economics_model` placement** — whether the economics model stays in PULSE
   as contract configuration or moves out with the engine. Deliberately undecided here: D6
   (the episode's `reported` terminal) hinges on it and its deciders are named in the D6
   record. The registry entry for cpt-om notes the dependency; nothing in this change
   forecloses either answer.
2. **cpt-om's outbound read surface.** The registry entry names the published warehouse
   surfaces (`docs/contracts/publishes.md`) as the outbound seam, which is what exists today.
   If cpt-om later needs sub-day freshness it attaches a bus rule + queue like any consumer —
   a registry status flip, not a design change.

## Risks / Trade-offs

- **The registry can rot.** Mitigated three ways: the shape test fails on malformed rows; the
  repo-resident-producer test (task 3.1) fails when an ingress package exists without a row;
  and `excluded-by-design` makes deliberate absence explicit, so rot is detectable as a
  vocabulary violation rather than a judgment call.
- **A deny-list is not a type system.** A monetary field named innocently (`monthly_value`)
  would pass. Accepted: the deny-list is a tripwire backing a stated contract, not the
  contract itself; review owns the judgment, the test owns the obvious cases.
- **cpt-om integration is unbuilt.** The registry row says `spec-only`, honestly. The contract
  this change writes is what makes that status safe to publish.

## Migration Plan

Docs and tests only — no catalog bump, no migration, no deployed surface changes. Tasks land
by PR in two waves (registry + boundary docs and their tests; then the AGENTS.md convention,
serial). Rollback is `git revert` of any landed PR; nothing external consumes the registry
until cpt-om's connector work begins against it.
