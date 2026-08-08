# Proposal — twenty-kanban-webhook-ingress

## Why

The Twenty kanban webhook route (D8) shipped in S1.1 task 3.4 deliberately disabled: the HMAC
middleware (`pulse_ledger.auth.verify_signature`, `TwentyWebhookConfig`) and the route's shape
exist and are tested, but the handler returns 501 — "drag → command is S2's to write"
(`pulse_ledger/api.py`). D15 closed 2026-08-06 (ADR-0004: shared-secret HMAC, quarterly rotation,
secret in the platform secret store, never in workflow config), which was the gate. This change
completes and enables the route: a kanban card drag becomes an attributed command on the ledger's
single write path, and an invalid drag (illegal transition per the catalog) produces a rejection
receipt plus a comment on the card. It is one of the four sanctioned command sources in the Phase 2
exit criteria and carries the "HMAC-signed synthetic drag → commit; invalid drag → rejection
receipt" leg of the Demo 2 receipt.

## What Changes

- **The `/webhooks/twenty` handler is implemented** — the 501 stub in `pulse_ledger.api` is
  replaced with the real ingress: `verify_signature` (unchanged) guards the door, a mapped drag
  becomes a `declare_transition` on the same injected `Committer` the bearer routes use. The route
  stays environment-gated (`PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED`); enabled-without-secret remains
  a boot failure. No auth is rebuilt.
- **Attribution per D15**: the webhook path's actor derives from the HMAC credential — a fixed
  webhook principal — never from a body field (ADR-0003 spoof-rejection posture). The Twenty
  workspace member who dragged the card travels as evidence provenance, not as actor.
- **Drag → command mapping** (`pulse_ledger/twenty/mapping.py`): a status-field update on a mapped
  board resolves subject type and key from the record's canonical identifiers
  (`design/platform/twenty-data-model.md`) and yields exactly one `declare_transition`; every
  other CRUD notification is acknowledged as a no-op. Idempotent under webhook redelivery via the
  D16 key.
- **Rejection feedback**: an illegal transition (the catalog's 422, unchanged) becomes a
  structured rejection receipt naming the violated transition and catalog version, plus a card
  comment posted back to Twenty.
- **Thin outbound Twenty comment client** (`pulse_ledger/twenty/client.py`): comment-create only —
  the one new external surface this change introduces (no Twenty API client exists in the repo).
  Faked at the client boundary in every test; no live Twenty instance exists until Phase 3.
- **Rotation support**: `TwentyWebhookConfig` gains an optional second accepted secret so the D15
  quarterly rotation is a config change with no rejection window; runbook
  `docs/runbooks/twenty-webhook.md` covers provisioning, enablement, and the rotation procedure.
- **Demo 2 slice**: `scripts/demo/demo2_kanban_drag.py` drives an HMAC-signed synthetic drag end
  to end offline — commit, then an invalid drag to rejection receipt and comment — the kanban leg
  of the Demo 2 exit criterion (the full receipt closes with `producer-ingress-policy`).

**Non-goal (explicit boundary):** the heal-back write — moving the card back to its true column
after a rejection — is Phase 3's `twenty-projection`, which closes D8 end to end. This change's
scope ends at rejection receipt + card comment.

## Capabilities

### New Capabilities

- `twenty-webhook-auth`: HMAC verification and freshness at the webhook door, dual-secret
  rotation, and D15 attribution — the actor is the credential's principal, the dragging user is
  provenance.
- `twenty-drag-command`: CRUD-noise filtering, drag → `declare_transition` mapping, canonical
  subject resolution, and idempotency under webhook redelivery on the single write path.
- `twenty-rejection-feedback`: the rejection receipt, the card comment via the outbound adapter,
  comment-failure semantics, and the PHI limits on everything that leaves the process.

### Modified Capabilities

_None. `command-api` is consumed as shipped: the webhook funnels into the same `Committer`, the
same catalog validation, and the same rejection surface — no requirement of the write path
changes. The HMAC middleware and its freshness window are S1.1 task 3.4 behavior, referenced not
re-specified._

## Impact

- Modified: `packages/pulse-ledger/src/pulse_ledger/api.py` (the 501 stub becomes the handler),
  `pulse_ledger/auth.py` (`TwentyWebhookConfig` second-secret field; `verify_signature` accepts
  either). New: `pulse_ledger/twenty/` (mapping + comment client), fixtures, runbook, demo script.
- Consumes S1.1 surfaces as shipped: `verify_signature` / `TwentyWebhookConfig` /
  `SIGNATURE_HEADER` / `TIMESTAMP_HEADER`, the injected `Committer`
  (`pulse_ledger.idempotency.commit_idempotent` in the running service),
  `IllegalTransitionError`'s reason + catalog version, `pulse_core.generated.
  DeclareTransitionCommand` vocabulary, `pulse_core.idempotency.derive_idempotency_key` (D16).
- New external surface: the Twenty REST comment endpoint, registered in
  `docs/contracts/consumes.md`. No live instance exists (D4 / `environment-matrix` is Phase 3):
  everything tests against recorded/synthetic payloads at the client boundary,
  `--disable-socket`; the payload contract is re-verified against a live instance in Phase 3.
- PHI: webhook payloads carry Twenty record fields (patient names) into the handler. No payload
  reaches a log, receipt, or comment — same posture `pulse_ledger.api` already documents.
  Fixtures are synthetic only.
- Rollback: unset `PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED` — the route disappears from the app, the
  ledger keeps every committed event. No migration, no data change.
