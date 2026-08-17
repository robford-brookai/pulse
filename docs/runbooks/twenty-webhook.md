# Runbook: twenty-webhook

Operator actions for the Twenty kanban webhook ingress (D8,
`openspec/changes/twenty-kanban-webhook-ingress/`): enabling `POST /webhooks/twenty`, the
quarterly dual-secret rotation, reading the disposition log, and the boundary this change stops
at. The route is `pulse_ledger.api`'s handler; payload interpretation is
`pulse_ledger.twenty.mapping`; the outbound card comment is `pulse_ledger.twenty.client`.

## Enablement

The route ships env-disabled. Three variables turn it on, and **all three come from the platform
secret store — never from workflow config, code, or a `.env` file committed anywhere**:

| Variable | Purpose |
| --- | --- |
| `PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED` | Truthy value (`1`/`true`/`yes`/`on`) mounts `POST /webhooks/twenty` on the app. Unset or falsy, and the route does not exist. |
| `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET` | The HMAC secret Twenty signs deliveries with (`pulse_ledger.auth.sign`, `X-Twenty-Webhook-Signature` / `X-Twenty-Webhook-Timestamp`, bare hex HMAC-SHA256 over `{timestamp}:{body}` with a millisecond timestamp, 5-minute freshness window — Twenty's own wire format per the task 4.2 capture). |
| `PULSE_LEDGER_TWENTY_API_TOKEN` | Bearer token for the outbound comment adapter (`pulse_ledger.twenty.client`, `POST /rest/comments`). Required only if a rejection comment will ever post — enabling the webhook route without it means rejections still produce a receipt, but the comment call fails at boot resolution (`TwentyApiTokenMissingError`). |

Enabling with `PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED` set but neither
`PULSE_LEDGER_TWENTY_WEBHOOK_SECRET` nor its rotation partner (below) set is a boot failure
(`TwentyWebhookSecretMissingError`), not a route that silently accepts everything. A secret
variable set to an empty or whitespace-only value is refused the same way
(`TwentyWebhookBlankSecretError`) — a blank is never read as "unset."

Board wiring (which Twenty object and status field map to which ledger subject) is static config
passed to `create_app` alongside these env vars, not itself an env var — see
`pulse_ledger.twenty.mapping.BOARD_MAPPINGS` for the v1 mapping.

Rollback is unsetting `PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED`: the route disappears from the app,
every already-committed event remains. No migration, no data change.

## Quarterly dual-secret rotation

`TwentyWebhookConfig` accepts a signature valid under either `secret` or `secret_next`
(`PULSE_LEDGER_TWENTY_WEBHOOK_SECRET_NEXT`), so rotation has no window where a correctly signed
delivery is rejected:

1. **Set `secret_next`.** Generate a new secret in the platform secret store, set
   `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET_NEXT` to it, deploy. Both the current and incoming secret
   now verify.
2. **Re-point Twenty.** Update the webhook's configured signing secret in Twenty to the new
   value. Deliveries signed with either secret continue to verify during this step — nothing to
   sequence carefully here.
3. **Promote.** Once Twenty is confirmed signing with the new secret (a run of `committed`/
   `replayed`/`noop`/`unmapped` dispositions with no `401`s in the access log), copy the new value
   into `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET` and deploy.
4. **Unset `secret_next`.** Remove `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET_NEXT` and the old secret
   from the secret store. A request still signed with the retired secret now fails verification
   (`InvalidSignatureError` → 401) — expected once this step completes, not before.

Each step is a config-only deploy; no code changes, no downtime. Do not skip step 4 — a retired
secret left in `secret_next` (or worse, left as the sole value in `secret`) is a credential nobody
is tracking as live.

## Disposition log vocabulary

Every webhook delivery past signature verification logs exactly one line:
`/webhooks/twenty disposition=<value> <facts>` (`pulse_ledger.api._log_disposition`), where facts
are identifiers, states, and reason codes only — never payload content. The response body carries
the same disposition (design decision 5: auth fails loud with a 401, everything else succeeds
quietly with a 200, because Twenty cannot act on an error status and retries a non-2xx forever).

| Disposition | Meaning | Ledger write |
| --- | --- | --- |
| `committed` | A mapped, subject-resolved, legal drag was declared. Response carries the event id. | Yes — new event |
| `replayed` | Twenty redelivered a notification already committed (D16 idempotency key from the webhook event id). Response carries the original event id. | No — returns the prior result |
| `noop` | Verified payload that is not a mapped status-field drag: other object, create/delete, an update not touching the mapped status field. | No |
| `unmapped` | A mapped drag whose record lacks its canonical identifier. Logs the Twenty record id and board only. | No |
| `rejected` | A mapped, subject-resolved drag whose target state is illegal per the catalog. Response is the rejection receipt (from-state, to-state, catalog reason, catalog version, card ref); a card comment is attempted via the outbound adapter. | No |
| `malformed` | The body is not the shape Twenty documents (missing/unreadable JSON, an expected field absent). Not in decision 5's list — it cannot become a valid disposition regardless of auth. | No |
| `error` | The handler raised for a reason that is not one of the above verdicts. Maps to a 500 (Twenty will redeliver it) rather than a disposition — the delivery was not actually handled. | No |

A `401` (missing/invalid signature, stale timestamp) never reaches this log — it is logged
separately by the existing auth-failure handler, with no body or signature content.

## Heal-back boundary

This change's scope ends at the rejection receipt plus the card comment. A rejected drag leaves
the Twenty board showing the column the user dragged to — **the card sits in the wrong column
until Phase 3's `twenty-projection`** closes D8 end to end by writing the card back to its true
state. The ledger itself is never wrong: the rejected drag wrote no event, so the ledger's state
for that subject is exactly what it was before the drag. Only the Twenty board view lags, and the
comment is the interim signal to the user who dragged it — it names the attempted transition, the
catalog reason, and that the state of record is unchanged. Do not treat a stuck card as a ledger
bug; treat it as expected until the heal-back write ships.

## Verifying board wiring

To confirm the route is live and correctly wired without waiting for real Twenty traffic:
`uv run python scripts/demo/demo2_kanban_drag.py` drives an HMAC-signed synthetic drag through a
fake committer and fake comment transport end to end — a committed drag, an illegal drag to a
rejection receipt plus a captured comment, and a tampered signature to a 401 — printing each
receipt. It runs offline (no live Twenty instance exists before Phase 3) and is not part of
`task check`.
