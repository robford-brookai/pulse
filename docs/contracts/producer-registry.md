# Producer Registry

The authoritative list of every system that crosses PULSE's boundary: declares into the ledger,
consumes what PULSE publishes, or both. One row answers "what crosses, in which direction,
through which seam, as whom, and is it real yet" — this document supersedes inference from a
credential list or a migration ADR.

**This registry is the contract, not the legacy surface inventory.** The "~11 surfaces" list in
`packages/ocean/docs/pt-data-infra-acq-status.md` describes where patient facts lived before the
connector architecture — no direction, no seam, no credential, vendor systems mixed with
infrastructure. Read this registry to integrate; read the legacy list only for historical context
on the problem PULSE replaces.

A system that declares into PULSE or consumes its published surfaces without a row here is a
defect, not a variant — see the standing rule in `AGENTS.md`. There is no grandfathering.

`Direction` is one of `declares in | consumes out | both`. `Status` is one of `shipped |
spec-only | planned | blocked | excluded-by-design`.

| System | Direction | Seam | Credential / actor | Grain | Status | Notes |
|---|---|---|---|---|---|---|
| Twenty kanban webhook | declares in | `POST /webhooks/twenty` (command API) | fixed webhook principal `twenty-webhook`, actor_type `system` (D15 — never a payload field) | one `declare_transition` command per kanban card drag | shipped | D8; heal-back on invalid drags; runbook `docs/runbooks/twenty-webhook.md` |
| Customer.io consent ingress | declares in | command API, via `packages/consent-ingress` reading the delivered `streamline.cio_raw`/`cio_prod` Snowflake landing | per-service credential, actor `customer.io` | one `communication_consent` transition per `{subject_key}:{channel}` event | shipped | D9, ADR-0005; Customer.io is the system of record and adjudicates suppression at send time — the ledger records, never blocks |
| Identity-resolution service | both | inbound: consumes `referral.received` off the event bus (`packages/identity`, `identity.service`); outbound: declares `resolve_referral` / `mint_person` / `attach_identifier` through the command API | per-service credential for `packages/identity` | one resolution decision per `Referral` (match, mint, or quarantine) | shipped | deterministic v1 only — no probabilistic scoring; quarantine goes to a human, never auto-merged |
| Warehouse verdict relay | declares in | command API, via `packages/verdict-relay` reading the dbt-computed verdict mart | per-service credential scoped to its own `writer_id` (durable cursor) | one `declare_verdict` (+ paired `declare_transition` per `transition_by_outcome`) per `(subject_id, verdict_type, run)` mart row | shipped | I3; `docs/contracts/consumes.md` pins the mart's row contract; registered `verdict_type` values only — an unregistered type fails validation before any API call |
| Human actors via attributed tooling | declares in | command API, via dashboard/CLI tooling issuing commands under a human's own credential | per-human credential, actor = the authenticated individual (D15) | one command per attributed human action | shipped | attribution is authentication — the actor is derived from the credential, never read from a body |
| cpt-om CPT revenue model | both | inbound: command API, under its own credential, declaring `billing_eligibility` verdicts; outbound: the published warehouse surfaces per `docs/contracts/publishes.md` | its own per-service credential, actor = the cpt-om model version (`rule_version`) | one `billing_eligibility` verdict per billing-episode evaluation | spec-only | direct-declare per `billing-computation-boundary` design decision 1 (the `customerio-consent-ingress` precedent, ADR-0005); declares qualification only — no monetary value crosses in, per `billing-computation-boundary` |
| Billy | declares in | command API, connector not yet built | planned per-service credential, actor `billy` (D9-pattern external system of record) | TBD — one row per Billy time-entry/episode transition (design pending) | planned | satellite billing app; recorded as an external SoR the same way Customer.io is, once a connector exists |
| POCAR | declares in | command API, connector not yet built | planned per-service credential, actor `pocar` | TBD — one row per POCAR care-coordination record transition (design pending) | planned | Mongo Atlas operational heart; satellite-store connector blocked per `design/migration/bf0-mongo-archaeology-agent-batch.md` |
| PAP standard connector | declares in | command API, standard-connector template (spec not yet written) | per-service credential, actor `pap` | TBD — one row per PAP intake event (template grain not yet pinned) | spec-only | satellite intake app; awaits the standard-connector template this row will bind to |
| Zendesk (Case mirror) | declares in | none — no ledger machine exists to declare into | none | none | excluded-by-design | Case stays a read-only mirror of the Zendesk ticket — no ledger state machine exists for it, and none is planned; PULSE never adjudicates or records Case transitions. Direction states the hypothetical had Case been included; nothing actually crosses |

## See also

- [`publishes.md`](publishes.md) — what PULSE exposes for a `consumes out` or `both` entry's
  outbound seam.
- [`consumes.md`](consumes.md) — the source-side detail for an ingress package's inbound read
  (mart contracts, export schemas).
- [`billing-boundary.md`](billing-boundary.md) — the amount-free contract the cpt-om row's Notes
  cite: PULSE records qualification, computes no monetary value, and the episode ends at
  `reported`.
