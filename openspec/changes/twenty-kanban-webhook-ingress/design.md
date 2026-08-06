# Design — twenty-kanban-webhook-ingress

## Context

See proposal.md — Why. Constraints that shape the design:

- The door already exists. `pulse_ledger.auth` ships `verify_signature` (HMAC over
  `{version}:{timestamp}:{body}`, freshness before HMAC, injected `now`), `sign`,
  `SIGNATURE_HEADER` / `TIMESTAMP_HEADER`, and `TwentyWebhookConfig` (env-gated,
  enabled-without-secret is a boot failure). `pulse_ledger.api.create_app` registers
  `/webhooks/twenty` only when enabled, calls `verify_signature`, then returns 501: "Signed here;
  drag → command is S2's to write." This change writes what is behind the door; it does not
  rebuild the door.
- The write path is injected: the route hands a `Declaration` and an idempotency key to the app's
  `Committer` (`pulse_ledger.idempotency.commit_idempotent` in the running service) — the same
  callable the bearer routes use, which keeps "single write path" structural and lets everything
  test without a database.
- D15 (ADR-0004, closed 2026-08-06): shared-secret HMAC for the webhook path, quarterly rotation,
  secret in the platform secret store, never in workflow config. Attribution is authentication —
  ADR-0003's spoof posture: the body never names the actor.
- No live Twenty instance exists (D4 / `environment-matrix` are Phase 3). Every test runs against
  recorded/synthetic webhook payloads at the client boundary, `--disable-socket`. The payload
  shape is pinned from Twenty's documented webhook format
  (`record.updated` with `record`, `updatedFields`, workspace member) plus
  `design/platform/twenty-data-model.md`; a Phase 3 task on `pulse-app-scaffold`'s ladder
  re-verifies it live before production enablement.
- The kanban grain: a board is a view over a SELECT status field on a Twenty object
  (`twenty-data-model.md` — e.g. PatientProgram `lifecycleStatus`); the subject grain and
  canonical key come from the object model, not from Twenty record IDs, which are internal only.
- Catalog legality is already enforced: `IllegalTransitionError` carries `reason`,
  `catalog_version`, `from_state`, `to_state` — the rejection receipt is a re-presentation of
  that, not new validation.

## Goals / Non-Goals

**Goals:**

- The enabled route is complete: signed drag → attributed `declare_transition` → commit or
  rejection receipt + card comment, end to end offline (the Demo 2 kanban leg).
- Rotation is operational from day one: dual-secret acceptance plus a runbook, because D15 made
  quarterly rotation a standing obligation, not a someday.
- PHI containment identical in kind to `pulse_ledger.api`'s existing posture, extended to the two
  new exits (receipt, comment) and asserted across every failure path.

**Non-Goals:**

- **No heal-back write.** Moving the card back to its true column after a rejection is Phase 3's
  `twenty-projection` (which closes D8 end to end). This change ends at rejection receipt + card
  comment; a rejected card visibly sits in the wrong column until then. Deliberate: heal-back is
  a projection write and belongs with the projection consumer's ordering guarantees, not here.
- No general Twenty API client — the outbound adapter is comment-create only. Phase 3 decides
  whether to extend or extract it.
- No human-actor attribution. The dragging workspace member is evidence, not actor (decision 2);
  upgrading them to a `human` actor requires Twenty-side signed user identity that does not
  exist.
- No production enablement. The env switch stays off everywhere until the D14 SPCS spike and
  Phase 3 environment work; this change makes "on" complete and safe, not "on" the default.
- No board-mapping admin surface: mappings are static service configuration (decision 3).

## Decisions

1. **The route body lives in `pulse_ledger/twenty/`, not inline in `api.py`.** `api.py` keeps
   what it already owns (auth at the door, error → status mapping, response shaping); the new
   module owns payload interpretation (`mapping.py`) and the outbound comment client
   (`client.py`). The mapping core is pure — payload + board mappings in, a typed disposition
   out (`Drag(declaration_fields, card_ref, member_ref) | NoOp(reason) | Unmapped(record_ref)`) —
   so it tests without an app, a database, or a socket.
   *Alternative rejected:* growing the handler inline in `api.py` — the module's docstring
   deliberately scopes it to auth/attribution/coercion, and a 200-line payload interpreter inside
   it breaks the file-size and single-concern rules.
2. **Attribution: a fixed webhook principal; the dragging user is evidence.** The HMAC credential
   authenticates *Twenty*, not a person, so per D15 the command commits as actor_type `system`,
   actor_id = the webhook principal (`twenty-webhook`), producer `twenty-webhook` — reusing
   `Writer.attribution()` with a constant `Writer` so the stamp is the same code path the bearer
   routes use. The workspace member from the payload goes into `evidence`
   (`{"system": "twenty", "ref": "workspaceMember:<id>"}` plus the record ref), satisfying the
   command-api rule that system actors carry evidence, and preserving who-dragged for audit.
   *Alternative rejected:* actor_type `human` with actor_id from the payload's workspace member —
   that is exactly the body-supplied actor ADR-0003 rejects as spoofable; nothing in the HMAC
   proves which human dragged.
3. **Board mappings are static, env-shaped config on the app** (object + status field →
   subject_type + canonical-key field), passed into `create_app` beside `TwentyWebhookConfig`,
   with one v1 mapping. A drag payload outside the mappings is a no-op, so Twenty's CRUD noise
   (the two-vocabularies rule in `event-envelope-spec.md`) never reaches the committer.
   *Alternative rejected:* deriving mappings from the catalog — the catalog knows subjects and
   transitions, not which Twenty object/field projects them; that wiring is
   `pulse-app-scaffold`'s codegen (D4), not guessable now.
4. **Idempotency: the D16 key derives with the Twenty webhook event id as logical time**
   (`pulse_core.idempotency.derive_idempotency_key`, writer `twenty-webhook`), so an at-least-once
   redelivery of the same notification is a replay by construction, while a genuine re-drag (new
   webhook event) is a new command. Mirrors `s14-identity` design decision 5's audit-key
   reasoning: the delivery's identity, not the wall clock, is the logical time.
   *Alternative rejected:* hashing the payload body — two legitimate identical drags (drag away,
   drag back, drag away again) could collide across deliveries depending on Twenty's timestamp
   fields; the event id is the honest delivery identity.
5. **Response semantics: auth fails loud, dispositions succeed quietly.** 401 for
   signature/freshness failures (existing handlers, unchanged) — a misconfigured secret must be
   visible in Twenty's delivery log. Everything after auth returns 200 with a disposition body:
   `committed` (event id), `replayed`, `noop`, `unmapped`, or `rejected` (the receipt). Twenty is
   not a client that can act on a 422, and a non-2xx makes Twenty retry — redelivering a rejected
   drag forever. The receipt, the comment, and the structured log are the feedback channels; the
   route never raises `IllegalTransitionError` to the app's 422 handler.
   *Alternative rejected:* passing the 422 through "for consistency with `/commands`" —
   consistency with a bearer SDK client that classifies statuses buys a retry storm from a
   webhook sender that classifies only 2xx/non-2xx.
6. **The comment client is deliberately thin and honestly flagged.** `client.py` is the one new
   external surface in this change: comment-create against Twenty's REST API, bearer-token env
   credential (`PULSE_LEDGER_TWENTY_API_TOKEN`), bounded retry with backoff on 5xx/timeouts, no
   other verbs. Tested entirely at the HTTP boundary against recorded/synthetic responses under
   `--disable-socket`; registered in `docs/contracts/consumes.md` with the Phase 3 live
   re-verification named. Comment failure after retries logs (card ref only) and never disturbs
   the receipt — feedback degrades, correctness does not.
   *Alternative rejected:* deferring comments to Phase 3 with heal-back — the roadmap row and
   Demo 2 pin "rejection receipt **plus a card comment**" to this change; shipping half the
   feedback loop leaves the user who dragged with no signal at all.
7. **Rotation: `TwentyWebhookConfig` grows `secret_next`** (`PULSE_LEDGER_TWENTY_WEBHOOK_
   SECRET_NEXT`), and verification accepts a signature valid under either configured secret —
   each still constant-time via the existing `verify_signature`, tried in order. Rotation becomes:
   set `secret_next`, re-point Twenty, promote and unset. Runbook documents the quarterly
   procedure and the secret-store location. Enabled-with-neither-secret stays a boot failure.
   *Alternative rejected:* single-secret hard cutover — every rotation buys a window of rejected
   drags in production, turning a quarterly D15 obligation into a quarterly incident.

## Risks / Trade-offs

- **The payload contract is pinned from documentation, not a live instance** → the mapping core
  isolates the shape in one module with recorded fixtures; the Phase 3 live re-verification is
  named in `docs/contracts/consumes.md`; a shape drift breaks one module and its fixtures, not
  the route's auth or commit semantics.
- **No heal-back means a rejected card lies until Phase 3** → accepted deliberately (the roadmap
  splits it this way); the card comment is the mitigation — the user is told the move did not
  take and the state of record is unchanged. The ledger is never wrong; only the board view is.
- **200-on-rejection could mask a systematically misconfigured board** → every disposition is a
  structured log line with a counter-friendly shape (route, disposition, subject key, states,
  reason); an unmapped/rejected flood is observable without any payload content. Monitor wiring
  is the `observability` unit's job.
- **PHI in the consumed payload**: the webhook body carries Twenty record fields (patient names)
  into the handler, so this path processes PHI even though it stores none. Flagged exits, each
  tested with a caplog/receipt/comment scan for fixture demographic strings: (a) the handler's
  exception path — a naive `logger.exception` would serialize the payload; the handler logs
  record ID + disposition only; (b) the rejection receipt and comment body — built exclusively
  from `IllegalTransitionError` fields and the card ref, never from the payload; (c) the
  unmapped-record log — names record ID and board only; (d) the comment client's failure logging —
  card ref only, never the comment body's context or the payload.
- **A constant `Writer` for the webhook principal could drift from the bearer registry's
  semantics** → it is built from the same `Writer` dataclass and stamped through the same
  `attribute()` path, so the spoof rule and attribution shape stay one implementation.

## Migration Plan

No data migration. Deploy is a config event: the route ships complete but env-disabled;
enablement (Phase 3, post `environment-matrix` + D14 spike) is setting
`PULSE_LEDGER_TWENTY_WEBHOOK_ENABLED` + secret + API token from the secret store per the runbook.
Rollback is unsetting the switch: the route disappears from the app; committed events remain, as
they must.

## Open Questions

- Which Twenty comment REST shape (core `comment` object vs. workspace-scoped path) the live
  instance exposes — safely deferrable: it changes recorded fixtures and the adapter's URL
  construction, not the specs, the mapping core, or the task breakdown. Re-verified in Phase 3.
