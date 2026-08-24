# Billing Computation Boundary

**Does PULSE price anything? No.**

PULSE records that a billing episode *qualified* and which version of whose rules decided it.
Every code, rate, amount, and revenue optimization lives in a system outside PULSE, registered as
a row in [`producer-registry.md`](producer-registry.md). Clinics submit the claims. This page is
the contract that says so, stated here so an integrator does not have to infer it from an absent
field or read a migration assessment to find it.

## What PULSE records

Billing **qualification**, and nothing more:

| Recorded | Shape | Where it lives |
|---|---|---|
| The verdict | the catalog's trinary outcome — `qualified` / `not_qualified`, with `indeterminate` moving no state and requiring a reason | a `declare_verdict` command on the `billing_episode` subject |
| Which rules decided it | `rule_version`, a string naming a version of a rule set PULSE does not hold | a required field on the same command |
| Where the evidence is | `lineage_ref`, an opaque pointer into the deciding system's own record | the command's `lineage` object |
| The episode's own facts | counters and stamps — accrued minutes, activity count, reading days, the episode month | the episode's facts, per the object model; none of them monetary |

The verdict is declared once and read thereafter. PULSE does not re-derive, second-guess, or
recompute a declared verdict, and neither does anything downstream of it: a projection or a
consumer displays the recorded outcome and never evaluates eligibility rules itself.

## What PULSE does not compute

No PULSE component computes, derives, or infers a monetary value. Specifically, PULSE holds none
of the following, as state or as configuration:

- a rate, an allowed amount, a reimbursement, a revenue figure, a copay, or a claim total;
- a CPT or HCPCS code as ledger state;
- a fee schedule or a partner rate card;
- a code-ladder rule, a code group, or a regulatory gate evaluation;
- a revenue optimization — no rationing of clinician minutes against captured reimbursement.

These belong to the **registered external revenue model**: the `cpt-om` CPT revenue model, whose
row in [`producer-registry.md`](producer-registry.md) names its seam, its credential, and its
grain. It declares `billing_eligibility` verdicts into PULSE through the command API under its own
credential — the deciding system is the actor on the event (D15), so `rule_version` and
`lineage_ref` attribute the decision to the model that made it rather than to a relay that carried
it. Nothing monetary crosses in that direction.

## Where the episode ends

The billing episode's v1 lifecycle terminates at `reported` — the billing-ready episode delivered
to the clinic:

```
open → qualified ⇄ not_qualified → reported → closed
```

`reported` freezes the verdict; a post-report correction goes through reversal, never a re-verdict.
`billed → reconciled` is **reserved behind config** and not shipped: those states enter the
vocabulary only if a percent-of-collections contract makes claim-outcome ingestion necessary. This
is D6, resolved: PULSE stops at reported because what happens to the claim afterwards is the
clinic's and the payer's, and PULSE would be recording someone else's ledger.

**Open, and deliberately so:** whether `Contract.terms.economics_model` stays in PULSE as contract
configuration or moves out with the pricing engine is undecided. It is open question 1 of the
`billing-source-boundary` design and it is what D6 hinges on. Nothing on this page forecloses
either answer, and no code should assume one.

## Money in evidence, never in state

The boundary runs between **state** and **evidence**, not around a keyword.

A verdict's `payload` and its `lineage_ref` may carry monetary detail the deciding system used — a
copay figure, a benefit category, a rate card version — because evidence is opaque to PULSE. A
verdict body carrying that detail in its payload commits cleanly.

That detail is never promoted into the state vocabulary, a catalog field, or a projection's
written surface. It is retrievable from the event payload or through lineage, and from nowhere
else. No catalog state, status field, or projected board column carries an amount.

Two tripwires pin this, both offline:

- **Catalog** — `packages/pulse-core/tests/test_catalog_amount_free.py` fails if any subject's
  field, state, or transition-reason name contains a monetary term.
- **Command envelope** — `packages/pulse-ledger/tests/test_billing_boundary.py` proves both
  halves: a top-level monetary field on a declaration is **refused**, and the same figure inside
  `payload` is accepted.

## How commands get in

Only through the command API, under a registered credential. Applications cross the PULSE line as
connectors — in via the command API, out via the event bus or the published warehouse surfaces
(see [`publishes.md`](publishes.md)). There is no point-to-point write path and no direct table
write; the schema revokes it.

A declaration body carrying a top-level field the command has no place for is **rejected**, not
committed with the field dropped — `pulse_ledger.api` raises `UnknownDeclarationFieldError`. So a
top-level monetary field on a billing command is structurally impossible, and an amount refused is
strictly better than an amount silently discarded. A producer with no row in
[`producer-registry.md`](producer-registry.md) is a defect, not a variant.

## See also

- [`producer-registry.md`](producer-registry.md) — the registered systems that cross the boundary,
  including the `cpt-om` row that carries this seam.
- [`publishes.md`](publishes.md) — the outbound surfaces a revenue model reads.
- [`consumes.md`](consumes.md) — the mart contract behind the warehouse verdict relay, the seam
  for verdicts computed inside the warehouse rather than by an external model.
