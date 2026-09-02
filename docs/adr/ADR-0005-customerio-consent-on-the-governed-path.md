# ADR-0005: Customer.io Consent Data Joins the Governed Path

- **Status**: Accepted
- **Date**: 2026-08-08

## Context

`customerio-consent-ingress` — D9's forward consent ingress, actor `customer.io`,
message-level provenance — was the last Phase 2 change, held on two things ADR-0004 could not
close: confirmation of the export/webhook mechanism, and compliance sign-off riding the §3.1
compliance-owner role-fill (runtime-readiness). Every other Phase 2 change shipped by
2026-08-08; the phase's ADR §6 exit criterion ("all four sanctioned command sources live")
includes Customer.io ingress, so v2.0 hung on exactly this decision.

## Decision

**We will bring Customer.io consent data onto the governed single-write path.** The
organizational decision is made: the DNA team confirmed, and Tal — who owns compliance
sign-off — has signed off.

**Export mechanism, confirmed**: the Customer.io export already lands in Snowflake, database
`streamline`, schemas `cio_raw` (raw landing) and `cio_prod` (modeled). The ingress consumes
this delivered Snowflake landing — no live Customer.io API pull in v1, consistent with the
posture s13-schedules established for the consent sweep (a delivered export is the input; live
pull is a possible follow-on with its own decision).

## Consequences

- `customerio-consent-ingress` is unblocked — the final Phase 2 change proposes now. It
  inherits the pinned contracts already in the baseline: the `{subject_key}:{channel}`
  consent-grain composition (consent-reconciliation spec, binding on every
  `communication_consent` producer), D9's Customer.io-wins conflict rule, actor-as-
  authentication (per-service credential, ADR-0003/ADR-0004 D15), and the §4.4 producer gate
  it must stay green under.
- The consent sweep (s13) and the forward ingress read the same landing, so drift between the
  two paths is a query away rather than a systems question.
- Consent data reaching the ledger becomes attributed, provenance-carrying commands — the
  suppression export stops being a side-channel truth.
- Cost: the ingress takes a Snowflake read dependency (`streamline.cio_raw`/`cio_prod` are
  external, warehouse-side surfaces — registered in `docs/contracts/consumes.md` by the
  change), and schema drift in the Customer.io export becomes a monitored failure mode rather
  than someone's spreadsheet problem.

## Alternatives considered

- **Live Customer.io API/webhook pull**: rejected for v1 — a new external integration surface
  with its own auth, rate, and failure semantics, when the export already lands in the
  warehouse under the existing BAA and access controls. Remains the named follow-on if
  freshness requirements outgrow the export cadence.
- **Keep consent reconciliation-only (s13's sweep) with no forward ingress**: rejected — D9
  and the object model make Customer.io the consent authority; a sweep-only posture leaves the
  ledger perpetually correcting rather than recording, and fails the phase's four-sources exit
  criterion.

---

## Note (2026-09-02, `pulse-demo-closeout` design.md decision 9)

This ADR's Decision section names the actor `customer.io`. That spelling is unspellable as a
writer id: the command API derives every writer id from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>` by
lowercasing the suffix and mapping `_` to `-` (`pulse_ledger.auth._writer_id_from_suffix`), and no
suffix can ever produce a dot — no dev credential could exist for this ingress, surfaced by the
first `task stage:e2e:live` (issue #342). The ingress, its spec, and the producer registry now
name the actor `customer-io`, registered as `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`. This is a
spelling correction to match the credential system's real constraints, not a reversal of the
Decision above — Customer.io consent data is still on the governed path, still D9-attributed.

---

**The log is append-only.** A decision that no longer holds gets a new ADR and a status flip on
the old one — never an edit. The point is the history, not the current state; the current state
is the code.
