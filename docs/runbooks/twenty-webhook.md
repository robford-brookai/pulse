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
| `PULSE_LEDGER_TWENTY_API_TOKEN` | Bearer token for the outbound rejection-commentary adapter (`pulse_ledger.twenty.client`, `POST /rest/notes` + `POST /rest/noteTargets` — v2.30 has no `comment` object, task 6.7). Required only if a rejection note will ever post — enabling the webhook route without it means rejections still produce a receipt, but the commentary call fails at boot resolution (`TwentyApiTokenMissingError`). |

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
| `noop` | Verified payload that produces no command: other object, create/delete, an update not touching the mapped status field, or a status-field update whose target already equals the state of record (`reason=echo_of_record` — the echo a heal-back or projection write fires back at this route, terminated here rather than rejected). | No |
| `unmapped` | A mapped drag whose record lacks its canonical identifier. Logs the Twenty record id and board only. | No |
| `rejected` | A mapped, subject-resolved drag whose target state is illegal per the catalog. Response is the rejection receipt (from-state, to-state, catalog reason, catalog version, card ref); a card comment is attempted via the outbound adapter. | No |
| `malformed` | The body is not the shape Twenty documents (missing/unreadable JSON, an expected field absent). Not in decision 5's list — it cannot become a valid disposition regardless of auth. | No |
| `error` | The handler raised for a reason that is not one of the above verdicts. Maps to a 500 (Twenty will redeliver it) rather than a disposition — the delivery was not actually handled. | No |

A `401` (missing/invalid signature, stale timestamp) never reaches this log — it is logged
separately by the existing auth-failure handler, with no body or signature content.

## Heal-back boundary

Shipped with `twenty-projection`: on a `rejected` disposition the route synchronously writes the
card's status field back to the state of record — the same state the rejection receipt names as
unchanged — through the projection writer (`api_server.build_heal_writer` over
`twenty_projection.apply.ProjectionRestClient`), attributed to the projection identity,
alongside the rejection note. The ledger itself was never wrong: the rejected drag wrote no
event; the heal corrects only the board view.

The heal degrades exactly as the rejection note does, and independently of it: a failed heal
logs `heal_failed` with the card ref only, and the receipt is still returned — a broken heal
channel degrades board convergence, never rejection correctness, because the projection's
full-state write converges the card on the subject's next event regardless. The heal write's own
`patientProgram.updated` webhook echo terminates at this route in one bounce as `noop` with
reason `echo_of_record` (see the disposition table above): no command, no note, no second heal.

Wiring: the heal writer builds only when `PULSE_LEDGER_TWENTY_PROJECTION_TOKEN` and
`PULSE_LEDGER_TWENTY_BASE_URL` are both set. Absent either, the app still boots and rejections
still produce their receipt and note — the pre-projection behavior — with `heal_failed` in the
log. One known constraint: Twenty does not push externally-made record mutations to open browser
sessions, so a healed card visibly snaps back only on refresh. Consumer operations are
[`docs/runbooks/twenty-projection.md`](twenty-projection.md).

## Verifying board wiring

To confirm the route is live and correctly wired without waiting for real Twenty traffic:
`uv run python scripts/demo/demo2_kanban_drag.py` drives an HMAC-signed synthetic drag through a
fake committer and fake comment transport end to end — a committed drag, an illegal drag to a
rejection receipt plus a captured comment, and a tampered signature to a 401 — printing each
receipt. It runs offline (no live Twenty instance exists before Phase 3) and is not part of
`task check`.
