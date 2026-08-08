# Tasks — twenty-kanban-webhook-ingress

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. `deps` names
task numbers in this file; `—` means no dependency. Linear ids get bracketed in after
`task linear:sync`. Default model is `sonnet`, stated explicitly on every task; `opus` where a
wrong transition-commit, an auth hole at the newly enabled door, or a PHI leak past the process
boundary is the retrofit-expensive defect.

Every task ships its tests in the same commit (tests first per `AGENTS.md`). No live network in
any test (`--disable-socket`): no live Twenty instance exists until Phase 3, so webhook payloads
are recorded/synthetic fixtures, the commit path is faked at the injected `Committer`, and the
Twenty comment API is faked at the HTTP client boundary. Fixtures are synthetic only — no PHI
anywhere, and fixture demographics are recognizable fakes so the caplog scans can grep for them.
Scenario coverage is a bijection: each spec scenario is named inline `(spec: "...")` on exactly
one task.

---

## 1. Wave 0 — fixtures and rotation

- [x] 1.1 [DNA-873] `packages/pulse-ledger/tests/fixtures/twenty/` — synthetic Twenty webhook payloads
      pinned from the documented `record.updated` shape plus
      `design/platform/twenty-data-model.md`: a legal drag (status field old→new, canonical spine
      ID, workspace member), an illegal drag, a redelivery duplicate (same webhook event id), a
      record missing its canonical ID, non-drag noise (create, delete, non-status update, unmapped
      object), and a malformed body — each with recognizable fake demographics for the PHI scans.
      A `sign_fixture` test helper wraps `pulse_ledger.auth.sign` so tests produce valid, tampered,
      and stale signatures without duplicating the HMAC recipe. `fixtures/twenty/README.md` names
      each case. Test: a loader validates fixture shape; no live network anywhere.
      `[model: sonnet | deps: — | lane: repo_change | wave: 0]`
- [x] 1.2 [DNA-874] Dual-secret rotation in `pulse_ledger/auth.py`: `TwentyWebhookConfig` gains
      `secret_next` (`PULSE_LEDGER_TWENTY_WEBHOOK_SECRET_NEXT`); verification accepts a signature
      valid under either configured secret, each check constant-time via the existing
      `verify_signature`; enabled-with-neither-secret stays a boot failure; empty-string secrets
      refused. No change to the signing recipe, headers, or freshness window. Tests: a request
      signed with the incoming secret verifies while both are set (spec: "A request signed with
      the incoming secret verifies during rotation"); once `secret_next` is promoted and the old
      value removed, the retired secret is rejected as unauthenticated (spec: "A retired secret
      stops verifying once removed"); enabled-without-secret still refuses boot.
      `[model: opus | deps: — | lane: repo_change | wave: 0]`
      Model `opus`: an auth hole in secret acceptance (empty secret, wrong fallback order) is the
      retrofit-expensive defect — this code is the only lock on the door.

## 2. Wave 1 — mapping core and comment adapter

- [x] 2.1 [DNA-875] `pulse_ledger/twenty/mapping.py` — the pure drag → command core (design decision 1): board
      mappings as typed config (object + status field → subject_type + canonical-key field, one v1
      mapping); payload interpretation into a typed disposition —
      `Drag(declaration_fields, card_ref, member_ref)` / `NoOp(reason)` / `Unmapped(record_ref)`;
      declaration fields carry `event_type` `declare_transition`, `to_state` = the new column,
      subject from the board mapping + canonical spine ID (never the Twenty record ID),
      `effective_at` from the payload's update time, evidence refs for the workspace member and
      record; D16 idempotency key derived via `pulse_core.idempotency.derive_idempotency_key`
      with the webhook event id as logical time (design decision 4). Pure: no app, no socket, no
      committer. Tests (fixtures from 1.1): a status-field update on the mapped board yields
      exactly one declaration with the new column as target state (spec: "A status-field update
      on a mapped board yields one command"); create/delete/non-status/unmapped-object payloads
      each map to `NoOp` (spec: "A non-drag notification is acknowledged as a no-op"); subject
      type and key derive from the mapping + canonical ID, not the record ID (spec: "The
      canonical identifier resolves the subject"); a record lacking the canonical ID maps to
      `Unmapped`, never a guessed command (spec: "A record without a canonical identifier is
      refused, not guessed"); the redelivery fixture derives an identical idempotency key.
      `[model: opus | deps: 1.1 | lane: repo_change | wave: 1]`
      Model `opus`: a wrong transition-commit — wrong subject, wrong state, wrong logical time —
      is the retrofit-expensive defect; every ledger fact this route ever writes flows through
      this mapping.
- [x] 2.2 [DNA-876] `pulse_ledger/twenty/client.py` — the thin outbound comment adapter (the one new external
      surface, design decision 6): comment-create only against Twenty's REST API, bearer token
      from `PULSE_LEDGER_TWENTY_API_TOKEN`, bounded retry with backoff on 5xx/timeouts, no other
      verbs; plus `format_rejection_comment(receipt) -> str`, built exclusively from the
      receipt's states, coded reason, catalog version, and "state of record is unchanged" — never
      from payload fields. Tested entirely at the HTTP boundary against recorded/synthetic
      responses, `--disable-socket`. Tests: posting invokes the adapter once with the card
      reference and a body containing from-state, to-state, and catalog reason, and containing no
      demographic or payload field (spec: "The comment names the transition and reason, nothing
      else"); retry then permanent-failure surfaces a typed error naming the card ref only; the
      credential never appears in any error or log line.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`

## 3. Wave 2–3 — the enabled route

- [x] 3.1 [DNA-877] Enable the route in `pulse_ledger/api.py`: replace the 501 stub with the real handler —
      `verify_signature` first (now either configured secret, from 1.2), then the 2.1 mapping,
      then the injected `Committer`; attribution stamped through a constant webhook-principal
      `Writer` (`twenty-webhook`, actor_type `system`) reusing `Writer.attribution()` (design
      decision 2), with the workspace member and record refs in `evidence`; disposition responses
      per design decision 5 — 401 on auth failure (existing handlers), 200 with
      `committed`/`replayed`/`noop`/`unmapped` bodies; every disposition a structured log line
      (route, disposition, subject key, states — never payload content). Rejection handling is
      3.2's; this task may leave `IllegalTransitionError` propagating temporarily. Tests (app
      built with a fake committer, signed fixtures from 1.1): a validly signed drag reaches
      mapping and commits, response carrying the committed event id (spec: "A validly signed
      request is processed"; spec: "A signed synthetic drag commits end to end"); a tampered body
      is 401 with no committer call and no body/signature in the log (spec: "A tampered body is
      rejected without processing"); a stale timestamp is 401 (spec: "A stale timestamp is
      rejected"); the committed declaration's actor is the webhook principal and the workspace
      member appears only in evidence (spec: "The dragging user is provenance, not actor");
      redelivering the duplicate fixture returns the original result marked replayed with exactly
      one committer effect (spec: "Webhook redelivery is a replay, not a second event").
      `[model: opus | deps: 1.2, 2.1 | lane: repo_change | wave: 2]`
      Model `opus`: this task opens the door 3.4 deliberately kept shut — an auth-ordering or
      attribution hole here is the retrofit-expensive defect.
- [x] 3.2 [DNA-878] Rejection feedback in the route: catch the catalog rejection from the committer, build the
      rejection receipt (from-state, to-state, catalog reason, catalog version, card ref —
      exclusively from `IllegalTransitionError` fields and the mapping's card ref), return it as
      a 200 `rejected` disposition, and post the card comment via 2.2; comment failure after
      retries logs the card ref only and still returns the receipt. Harden the flagged PHI exits
      (design Risks) that this task introduces: the handler exception path logs record ID +
      disposition, never the payload. The unmapped-record log line is owned by 3.1 (a declared
      dependency) — this task asserts its record-ID-and-board-only content in the caplog scan
      but does not edit it. Tests: an illegal drag writes no event and
      returns the receipt naming from-state, to-state, reason, and catalog version (spec:
      "Illegal transition yields a receipt and no event"); a comment-post failure still returns
      the receipt and logs only the card ref (spec: "A comment failure never loses the receipt");
      a caplog + receipt + comment-body scan across every disposition — commit, no-op, unmapped,
      rejection, comment failure, malformed payload — finds no fixture demographic string (spec:
      "No fixture payload content in logs or receipts across failure paths").
      `[model: opus | deps: 2.2, 3.1 | lane: repo_change | wave: 3]`
      Model `opus`: the receipt and comment are the two new exits from the process — a PHI leak
      through either is the retrofit-expensive (and reportable) defect.

## 4. Wave 4 — proof and documentation

- [x] 4.1 [DNA-879] `scripts/demo/demo2_kanban_drag.py` — the Demo 2 kanban leg, offline per the demo
      convention (LocalStack/fixtures only, exits nonzero on any failed assertion, out of
      `task check`): build the app with a fake committer and fake comment transport, drive an
      HMAC-signed synthetic drag to a committed event id, then an invalid drag to a rejection
      receipt plus a captured card comment, then a tampered signature to a 401 — printing each
      receipt. Runbook section in 4.2 references it; receipt output attaches to the Linear parent
      before archive. Test: a smoke-parse test covers the script; the script runs green from a
      fresh checkout with no network.
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 4]`
- [ ] 4.2 `docs/runbooks/twenty-webhook.md` + contracts: runbook covers enablement (env switch +
      secret + API token, all from the platform secret store, never workflow config), the
      quarterly dual-secret rotation procedure (set `secret_next` → re-point Twenty → promote →
      unset), the disposition log vocabulary, and the heal-back boundary (rejected cards sit
      wrong until Phase 3's `twenty-projection`); register the Twenty comment endpoint in
      `docs/contracts/consumes.md` with the Phase 3 live re-verification named, and the webhook
      ingress endpoint + signing contract in `docs/contracts/publishes.md`. Tests:
      `mkdocs build -s` green; verification file-existence checks pass.
      `[model: sonnet | deps: 3.2 | lane: repo_change | wave: 4]`
      `serial: openspec_main_specs` — doc-updater lane: `docs/contracts/publishes.md`,
      `consumes.md`, and `mkdocs.yml` are cross-change shared surfaces (s13/s14/catalog-authority
      all touch them), so edits serialize even though no `openspec/specs/` file changes here.
- [ ] 4.3 Verification wrap — end to end on a fresh checkout:
      `ruff check packages/pulse-ledger && pyright packages/pulse-ledger`;
      `uv run pytest packages/pulse-ledger --disable-socket` (existing coverage gate unchanged);
      `uv run python scripts/demo/demo2_kanban_drag.py`;
      `grep -q "twenty-webhook" docs/contracts/publishes.md`;
      `test -f docs/runbooks/twenty-webhook.md`.
      Test: the block itself, plus `task check` green — any failure is fixed here before Agent
      Review.
      `[model: sonnet | deps: 4.1, 4.2 | lane: repo_change | wave: 4]`
