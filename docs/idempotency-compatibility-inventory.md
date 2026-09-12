# Idempotency compatibility inventory

The rollout gate for the D16 amendment (ADR-0007): enforcement of writer binding and canonical
request v1 stays off until every deployed producer that retries a command has a row here at a
disposition of `compatible` or `migrated`. Filed for `idempotency-integrity` task 1.1 as the
template the change fills in; task 2.2 added the reconstruction rules and the mechanism that
classifies the rows, task 3.2 adds the connector-side evidence, and the dispositions are decided by
task 4.1's attended run before any enforcement.

**Status as of task 2.2: every row is `unknown`, and enforcement is blocked.** That is the
inventory's correct state, not an omission — the classification is derived from a query against a
populated database, and no such run has happened. Nothing in this change may promote a row; the
mechanism below is what a reviewed run uses to fill them.

This page is a gate, not a report. A row at `fix-required` or `unknown` blocks enforcement, and
"no rows" is not a pass — an empty table means the inventory has not been taken.

## Why an inventory rather than a flag day

Idempotency keys are retained for the ledger's lifetime, so every key already stored is a key a
producer may still retry. The amendment refuses a replay it cannot bind to an authenticated writer
and a complete canonical request, and a legacy key has neither recorded. Whether that refusal is
safe is a property of the *producers*, not of the ledger: a producer that never retries is
unaffected, one that retries an unchanged request rebinds on first sight, and one that retries a
request the stored event cannot fully prove would start receiving `idempotency_legacy_unverifiable`
where it previously received a result. Only the third kind blocks, and only an inventory tells them
apart.

## How each column is decided

Evidence is derived, never asserted. Every row cites where its answer came from.

- **Producer** — a credential in `docs/contracts/producer-registry.md`, or the fixed signed-Twenty
  principal. One row per credential, not per service: the binding is per authenticated writer.
- **Ingress** — `bearer` (`POST /commands`), `batch` (`POST /commands:batch`), or `webhook` (signed
  Twenty). A producer that uses two ingresses gets two rows; the batch envelope and the webhook
  disposition classify conflicts differently.
- **Retries keyed** — does this producer send `idempotency_key` at all, and does it ever re-send
  one? Evidence: the producer's own submit path, plus observed repeat keys in
  `ledger.idempotency_keys` for its writer id (counts only — never request values).
- **Request reconstructible** — can the canonical v1 field set be proved in full from the stored
  event for this producer's keys? Evidence: a reconstruction run over a synthetic copy of its
  rows, reporting the count of keys whose fields are complete and the field names missing from the
  rest. Never a sample of values.
- **Varies between retries** — does the producer ever change the accepted request under one key (a
  widened payload, a corrected reason, a re-derived `effective_at`)? This is the population that
  turns from a silent replay into a 409, and the reason the inventory exists.
- **Disposition** — one of:
  - `compatible` — retries are exact and reconstructible; enforcement changes nothing for it.
  - `migrated` — bindings were derived and written for its legacy keys, verified by replay on a
    synthetic upgraded database.
  - `fix-required` — a producer-side change must ship before enforcement. **Blocks rollout.**
  - `unknown` — not yet audited. **Blocks rollout.**
- **Evidence** — a PR, test id, or runbook receipt. Counts, field names, writer ids and key
  digests only; no request payload values, no evidence contents, no fingerprints.

## What the ledger can prove about a legacy key

`pulse_ledger.legacy_binding` decides "request reconstructible" mechanically, from the original
event's own columns and nothing else. A key that passes every check below rebinds on its owner's
first retry and keeps replaying; a key that fails any of them receives
`idempotency_legacy_unverifiable`, keeps its lifetime reservation, and is never bound to a guess.

| Check | What it establishes | Reason recorded when it fails | Row disposition |
| --- | --- | --- | --- |
| `schema_version` is 1 | the stored shape is the one canonical v1 is written against | `unsupported_schema_version` | `unknown` |
| `reverses_event_id` is null | the event is a declared command, not a correction appended by `commit_reversal` | `correction_event` | `fix-required` |
| `producer` = `actor_id`, `actor_type` = `system` | one resolved credential stamped the attribution, so the writer is authenticated and not a string in a column (D15) | `unattributed_writer` | `fix-required` |
| `evidence_bound_lower` and `..._upper` are both set or both null | the pair is determined; one half would have to be assumed | `incomplete_evidence_bounds` | `fix-required` |
| the rebuilt request fingerprints | the value has a canonical spelling, the same way it would have needed one at ingress | `unfingerprintable_request` | `fix-required` |

The split between `fix-required` and `unknown` is load-bearing: the first is a decided answer that
needs a producer-side change, the second is a shape this build cannot read and needs a field map
before anyone can say. Both block the rollout; they name different follow-ups.

## How a row is filled

`inventory_legacy_keys(conn)` runs the checks above over every retained key, groups them by the
producer of the event each key claims, and gives a producer the **worst** disposition any of its
keys holds — one unreconstructible key is never averaged away by a thousand compatible ones. It
returns producer ids, key counts, per-disposition counts and reason *names*; it cannot return a
request value or a fingerprint, which is why it is safe to paste its output into this page.

The run belongs to the attended rollout preflight (task 4.1) against a synthetic populated copy of
pre-binding rows, not to a worktree job and not to production. Its output replaces the `unknown`
rows below, with the run's receipt as the evidence.

## Inventory

One row per credential that submits commands, from `docs/contracts/producer-registry.md`, plus the
fixed signed-Twenty principal. "Retries keyed" and "varies between retries" are producer-side facts
and stay at `unknown` until each producer's submit path is audited (task 3.2).

| Producer | Ingress | Retries keyed | Request reconstructible | Varies between retries | Disposition | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `twenty-webhook` (signed Twenty principal) | webhook | `unknown` | `unknown` — not yet run | `unknown` | `unknown` | — |
| `verdict-relay` (warehouse verdict relay) | bearer | `unknown` | `unknown` — not yet run | `unknown` | `unknown` | — |
| `customer-io` (Customer.io consent ingress) | bearer | `unknown` | `unknown` — not yet run | `unknown` | `unknown` | — |
| identity-resolution service credential | bearer | `unknown` | `unknown` — not yet run | `unknown` | `unknown` | — |
| per-human credentials (attributed tooling) | bearer | `unknown` | `unknown` — not yet run | `unknown` | `unknown` | — |
| `billing-engine` (pulse billing engine / cpt-om) | bearer | `unknown` | `unknown` — spec-only, no deployed keys claimed yet | `unknown` | `unknown` | — |
| `billing-connector` (`BILLING_CONNECTOR_TOKEN`) | bearer | `unknown` | `unknown` — spec-only, no deployed keys claimed yet | `unknown` | `unknown` | — |
| `pap` (PAP standard connector) | bearer | `unknown` | `unknown` — spec-only, no connector built | `unknown` | `unknown` | — |
| `billy` | bearer | `unknown` | `unknown` — planned, no connector built | `unknown` | `unknown` | — |
| `pocar` | bearer | `unknown` | `unknown` — planned, no connector built | `unknown` | `unknown` | — |

A `spec-only` or `planned` producer is still `unknown` rather than trivially compatible: "this
credential has claimed no keys" is a statement about the ledger's contents, and it is true only
once a run says so. Zeroing it by assumption is the same mistake as an empty table.

## Rollout gate

Enforcement may be enabled only when all of the following hold, each recorded above:

1. Every credential in `producer-registry.md` that submits commands has a row, plus the
   signed-Twenty principal.
2. No row is at `fix-required` or `unknown`.
3. Every `migrated` row cites a replay verified on an upgraded database carrying a synthetic copy
   of pre-binding rows, not on a fresh schema.
4. The reconciliation path for any producer whose keys are not fully reconstructible is reviewed
   and recorded here, and its producer is at `compatible` or `migrated` by that path.
5. ADR-0007 is Accepted and ADR-0004's D16 subsection carries its status flip.

`LegacyInventory.enforcement_blocked` encodes conditions 2 and the empty-table rule directly, so
"the gate is clear" is a value a preflight can read rather than a judgement someone makes by
looking at the table. It is true while any row is `fix-required` or `unknown`, **and** true for an
inventory with no rows at all. Conditions 1, 3, 4 and 5 stay human review on this page.

A rollback after enforcement re-opens the pre-amendment collision behaviour. It preserves binding
rows, and it is bounded and recorded on the rollout issue — never described as safe by default.

## Data handling

This page and the runs behind it carry no PHI and no request content: counts, field *names*,
credential ids, key digests and event ids only. A reconstruction run that needs to look at values
does so inside the process and reports names and counts; it never writes them here, into a log, or
into an issue comment.
