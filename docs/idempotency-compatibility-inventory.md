# Idempotency compatibility inventory

The rollout gate for the D16 amendment (ADR-0007): enforcement of writer binding and canonical
request v1 stays off until every deployed producer that retries a command has a row here at a
disposition of `compatible` or `migrated`. Filed for `idempotency-integrity` task 1.1 as the
template the change fills in; task 2.2 added the reconstruction rules and the mechanism that
classifies the rows, task 3.2 adds the connector-side evidence, and the dispositions are decided by
task 4.1's attended run before any enforcement.

**Status as of task 3.2: every disposition is `unknown`, and enforcement is blocked.** Task 3.2
filled the two producer-side columns — "retries keyed" and "varies between retries" — from the
submit paths committed in this repo, which is evidence a worktree can derive. "Request
reconstructible" stays unfilled because it is a query against a populated database, and no such run
has happened. Nothing in this change may promote a disposition; the mechanism below is what a
reviewed run uses to decide them, and the attended rehearsal that runs it is
[`docs/runbooks/idempotency-enforcement-rollout.md`](runbooks/idempotency-enforcement-rollout.md).

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
fixed signed-Twenty principal. "Retries keyed" and "varies between retries" are producer-side facts,
audited in task 3.2 from each submit path in this repo and cited to the line or the test that shows
it; a producer with no connector built has no submit path to read and stays `unknown`.
`packages/pulse-core/tests/test_idempotency_conflict_contract.py::TestRolloutPreflight` checks this
table mechanically: every registry row that can declare has a row here, the vocabulary is the one
this page defines, and a `unknown` or `fix-required` disposition blocks.

| Producer | Ingress | Retries keyed | Request reconstructible | Varies between retries | Disposition | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `twenty-webhook` (signed Twenty principal, Twenty kanban webhook) | webhook | `yes` — derived per delivery in `pulse_ledger.twenty.mapping._drag` over the delivered record, with `record.updatedAt` as the logical time; a redelivery re-derives the same key | `unknown` — not yet run | `no` for a redelivery — `to_state` and `evidence` are outside the key but are re-derived from the same delivery snapshot, so a redelivery reproduces them exactly. A *new* write reusing one `updatedAt` for a different destination column would keep the key and change the request | `unknown` | `test_idempotency_conflict_contract.py::TestSignedTwentyIngress` |
| `verdict-relay` (warehouse verdict relay) | bearer | `yes` — `PulseCoreClient.submit_command` derives one per mart row (`verdict_relay.declarer`), and the relay re-declares from its durable cursor after a restart | `unknown` — not yet run | `no` observed, with one configuration-shaped exception — the verdict's own fields come from the mart row, but the paired transition's `to_state` comes from the `transition_by_outcome` map and is outside the key, so re-declaring an old cursor position after that map changes keeps the key and changes the request | `unknown` | `verdict_relay/declarer.py:319`; `test_idempotency_conflict_contract.py::TestFieldsOutsideTheKey::test_to_state_varying_between_retries_conflicts` |
| `customer-io` (Customer.io consent ingress) | bearer | `yes` — one per landing row, `effective_at` = the row's own `event_time` (`consent_ingress.declarer`) | `unknown` — not yet run | `no` — `to_state` and the payload both come from the pinned landing-row contract, and the declarer sends no `evidence`, `evidence_class` or `epoch`, so every field of the canonical request is a function of the row | `unknown` | `consent_ingress/declarer.py:135`; row contract in `docs/contracts/consumes.md` |
| identity-resolution service credential (`packages/identity`) | bearer | `yes` — `identity.resolver._declare` submits under the SDK-derived key for each resolution decision | `unknown` — not yet run | **`yes`** — `evidence.candidate_count` and `evidence.matched_fields` travel in `evidence`, which is outside the D16 key and inside canonical request v1. Re-resolving one triggering event after further referrals land derives the same key with a different request, which is a 409 after enforcement where it is a replay today | `unknown` | `identity/resolver.py:398`; `test_idempotency_conflict_contract.py::TestFieldsOutsideTheKey::test_evidence_varying_between_retries_conflicts` |
| per-human credentials (human actors via attributed tooling) | bearer | `unknown` — the submit path is whatever tooling the human ran; nothing in this repo bounds it | `unknown` — not yet run | `unknown` — same reason | `unknown` | — |
| `billing-engine` (pulse billing engine / cpt-om) | bearer | `unknown` — spec-only, no deployed keys claimed yet | `unknown` — spec-only, no deployed keys claimed yet | `unknown` | `unknown` | — |
| `billing-connector` (`BILLING_CONNECTOR_TOKEN`) | bearer | `yes` in the built path — `billing_connector.declare` submits one evaluation snapshot through `submit_with_retry`; spec-only as a deployment, so no keys are claimed yet | `unknown` — spec-only, no deployed keys claimed yet | `no` in the built path, with the relay's configuration-shaped exception — the paired transition's `to_state` comes from `_TRANSITION_BY_OUTCOME` | `unknown` | `billing_connector/declare.py:158` |
| `pap` (PAP standard connector) | bearer | `unknown` — spec-only, no connector built | `unknown` — spec-only, no connector built | `unknown` | `unknown` | — |
| `billy` | bearer | `unknown` — planned, no connector built | `unknown` — planned, no connector built | `unknown` | `unknown` | — |
| `pocar` | bearer | `unknown` — planned, no connector built | `unknown` — planned, no connector built | `unknown` | `unknown` | — |

A `spec-only` or `planned` producer is still `unknown` rather than trivially compatible: "this
credential has claimed no keys" is a statement about the ledger's contents, and it is true only
once a run says so. Zeroing it by assumption is the same mistake as an empty table.

## The fields outside the key

The D16 key and canonical request v1 do not cover the same fields, and the gap is where every
compatibility risk in the table above lives.

| | In the D16 key | In canonical request v1 |
| --- | --- | --- |
| `subject_type`, `subject_key`, command/event type, `payload` | yes | yes |
| `logical_time` | yes | no — it is client-only and is never reconstructed |
| `effective_at` | only because `PulseCoreClient.submit_command` passes it as `logical_time` | yes |
| `to_state`, `epoch`, `evidence`, `evidence_class`, evidence bounds | **no** | **yes** |

A producer that varies a field in the last row between retries of one fact keeps deriving the same
key and starts receiving `idempotency_conflict` after enforcement, where it receives the original
result today. A producer that varies a field in the first row derives a *different* key and simply
commits a second event, exactly as it does now — which is why an ordinary payload change is not a
compatibility risk and a re-read evidence window is.

This is not a defect in either definition. The key cannot be widened without re-keying every
deployed producer, and the fingerprint cannot be narrowed without letting a changed request replay
another request's event, which is the disclosure ADR-0007 exists to close. It is a migration fact,
and the inventory is where it is tracked.

`packages/pulse-core/tests/test_idempotency_conflict_contract.py::TestFieldsOutsideTheKey` holds
each of these shapes as a test, in the form the deployed producers have them.

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
