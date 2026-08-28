# Proposal: billing-source-boundary

## Why

Nobody can currently answer, from this repo, where billing computation lives. Three facts,
each verifiable today:

- **PULSE holds billing-shaped state but computes nothing about money.** `billing_episode` is a
  catalog subject with a real lifecycle (`open → qualified ⇄ not_qualified → reported →
  closed`), `month-open` opens one per enrollment per month, and `verdict-relay` registers a
  `billing_eligibility` verdict type. None of it carries a monetary field. That is correct — and
  undocumented as a deliberate boundary rather than an omission.
- **The engine exists, in another repo, unaware of PULSE.** `robford-brookai/cpt-om` ("Brook CPT
  revenue model & nurse-capacity optimizer") owns 34 CPT codes, 19 standard rates, 19 partner
  rate cards, code ladders, prerequisites, four regulatory gates, and a MILP that rations
  nurse-minutes to maximize captured reimbursement. It mentions PULSE nowhere; PULSE mentions it
  nowhere. The only reference to a pricing engine anywhere in this repo is `billing-state`'s
  open question 3, which asks which seam it should use and leaves the answer blank.
- **The registry it should be listed in does not exist.** The "~11 surfaces" everyone cites
  (`packages/ocean/docs/pt-data-infra-acq-status.md`) is a legacy inventory of *where patient
  facts currently live* — HubSpot, Customer.io, PAP, ExDash, Billy, POCAR, RDS, MySQL, S3,
  Snowflake, Sigma — written to describe the problem, not to govern connectors. It predates the
  connector architecture, mixes vendor SaaS with infrastructure, and says nothing about
  direction, credential, or status. Meanwhile the governed list that does exist — the four
  sanctioned command sources — lives in prose in a migration ADR.

So a new engineer asking "does PULSE price anything?" has to infer the answer from the absence
of a field, and an engineer wiring cpt-om has no contract to write against.

## What Changes

- **State the billing computation boundary as a spec, not an inference.** PULSE records billing
  *qualification* (a trinary verdict plus the `rule_version` that decided it) and never computes,
  stores, or transmits a monetary amount: no rate, no allowed amount, no CPT code as state, no
  revenue, no optimization. The engine that does own those things is external by construction.
- **Register the CPT revenue model as a data source with a defined seam.** cpt-om becomes a
  producer *and* consumer: it reads what to evaluate from the ledger's own published surfaces
  (enrollment and coverage state, the episode's `accrued_minutes` and `reading_days` counters),
  and declares its result back through the command API under its own credential as a
  `billing_eligibility` verdict carrying `rule_version` and `lineage_ref`. This answers
  `billing-state` open question 3 by choosing the direct-declare option over the mart-feed
  option, for the reasons in design.md.
- **Establish a governed producer registry** in `docs/contracts/` — one row per system that
  crosses PULSE's boundary, each naming its direction (declares in / consumes out / both), its
  seam (command API, delivered export, bus subscription), its credential and actor id, and its
  status (shipped / spec-only / planned / blocked / deliberately excluded). The legacy
  ~11-surfaces list is superseded by it and cross-linked as the historical inventory.
- **Draw the amount-shaped-payload line in the ingress policy's terms.** A verdict payload may
  carry evidence that references money (a copay figure in `lineage_ref` detail, per
  `billing-state`'s Decision 2) but a *command* may never assert an amount as state, and no
  catalog subject may grow a monetary field. This is the billing analogue of the existing
  producer-policy classification test, and it is checkable offline.

## Capabilities

- `billing-computation-boundary` (new) — what PULSE does not compute, what it records instead,
  and the amount-free guarantee on commands and catalog states.
- `producer-registry` (new) — the governed registry: what every entry must state, and the rule
  that a system crossing the boundary without a registry entry is a defect.

## Out of scope

- **Building the cpt-om connector.** This change defines the contract and registers the source;
  the tap, mapper, and emitter are cpt-om's work against this contract, or a later
  `billing-eligibility-ingress` change here if the connector is to live in this repo.
- **The claims lifecycle.** D6 stands: the episode stops at `reported`, and `billed →
  reconciled` stays reserved behind config until a percent-of-collections contract forces
  claim-outcome ingestion.
- **`Contract.terms.economics_model`.** Whether the economics model stays in PULSE as contract
  configuration or moves out with the engine is a genuine open question (design.md, open
  question 1) — deliberately not decided here, because D6 hinges on it and the deciders are
  named elsewhere.
- **Retiring anything.** No billing state leaves PULSE: `billing_episode`, `month-open`, and the
  verdict→transition pairing all stay. The retired CPT material in `packages/ocean/docs/` was
  never migrated into PULSE and needs no removal, only a note that it describes a superseded
  architecture.
- **Billy, and the other unbuilt connectors.** The registry lists them with honest status; it
  does not build them.

## Entry conditions

- None blocking. `billing-state` is in flight and owns the `verdict-declare` and `coverage-state`
  deltas — this change writes no delta on either, and its registry entry for the verdict mart
  describes the surface that change is completing.
