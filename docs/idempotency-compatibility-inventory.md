# Idempotency compatibility inventory (template)

The rollout gate for the D16 amendment (ADR-0007): enforcement of writer binding and canonical
request v1 stays off until every deployed producer that retries a command has a row here at a
disposition of `compatible` or `migrated`. Filed for `idempotency-integrity` task 1.1 as the
template the change fills in; the evidence rows are written by tasks 2.2 and 3.2 and reviewed
before task 4.1's attended rehearsal.

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

## Inventory

| Producer | Ingress | Retries keyed | Request reconstructible | Varies between retries | Disposition | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| _(one row per credential — unfilled)_ | | | | | `unknown` | |

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

A rollback after enforcement re-opens the pre-amendment collision behaviour. It preserves binding
rows, and it is bounded and recorded on the rollout issue — never described as safe by default.

## Data handling

This page and the runs behind it carry no PHI and no request content: counts, field *names*,
credential ids, key digests and event ids only. A reconstruction run that needs to look at values
does so inside the process and reports names and counts; it never writes them here, into a log, or
into an issue comment.
