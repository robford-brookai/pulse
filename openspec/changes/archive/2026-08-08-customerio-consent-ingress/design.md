## Context

See proposal.md — Why. Constraints that shape the approach:

- ADR-0005 pins the export mechanism: Snowflake `streamline.cio_raw` (raw landing) / `cio_prod`
  (modeled), no live Customer.io API pull in v1. This is a delivered-export posture, the same one
  `s13-schedules`' consent sweep already established for the suppression export.
  `verdict-relay.mart_reader` is the closest existing pattern for a cursor-based Snowflake read:
  a `RowSource` protocol, a pinned row contract validated before any row is used, and a durable
  cursor through `pulse_core.cursor` (the ledger's writer-state facility).
  `packages/schedules.consent_sweep` is the closest existing pattern for consent-specific
  declaration: the `{subject_key}:{channel}` grain composition, D9 authority semantics, D15
  credential-as-attribution, D16 idempotency keyed off the input's own identity (not wall-clock),
  and a no-PHI drift receipt.
- `consent-reconciliation`'s spec already binds the `{subject_key}:{channel}` composition on
  "any other producer of `communication_consent` state (e.g. a forward consent ingress)" — this
  design does not choose that composition, it inherits it verbatim.
- Attribution is authentication (ADR-0003): the ingress's per-service `customer.io` credential
  (D15) is what makes every declared command's actor `customer.io` — no payload field ever names
  an actor.
- The §4.4 producer-policy gate (`openspec/specs/producer-policy`) scopes its classification to
  `packages/ocean` producer source. This package is not `packages/ocean` and declares exclusively
  through the command API client — the same posture `packages/schedules` and `packages/verdict-relay`
  already hold, neither of which the gate scans. Compliance here is structural (no catalog-state
  event vocabulary exists to flag), not gate coverage; Decision 5 makes this explicit so a later
  reader does not go looking for a suppression entry that would never be needed.

## Goals / Non-Goals

**Goals:**

- One package, cursor-resumable Snowflake reads, pinned row contract, D16 idempotent declaration
  keyed off the source row's own identity so a re-read (crash resume or full re-run) always
  replays.
- Reuse the two already-pinned patterns exactly: `mart_reader`'s `RowSource`/cursor shape for the
  read side, `consent_sweep`'s grain composition and no-PHI receipt shape for the declare side.
- Fail loudly on contract drift: a malformed row is counted and attached, never silently dropped;
  the run's exit status is the operational contract, same as `schedules`.

**Non-Goals:**

- No live Customer.io API/webhook pull (ADR-0005 alternatives — named follow-on with its own
  decision).
- No conflict resolution logic: this ingress is the forward *recording* path; reconciling drift
  between it and any other producer of `communication_consent` state is `consent-reconciliation`'s
  job, unchanged by this change.
- No scheduler/infra wiring in this change's initial scope beyond what a follow-on ops task adds
  — the CLI and its `--dry-run` are the operational surface; cadence wiring follows the
  `schedules`-package precedent (IaC config, applied outside the change) if and when a cadence is
  chosen, since ADR-0005 pins the export *mechanism*, not a read cadence.

## Decisions

1. **New package `packages/consent-ingress`, module `consent_ingress`.** *Alternative
   considered:* name the package after the change (`customerio-consent-ingress`). Rejected —
   ADR-0005 itself frames the vendor as the v1 export source, not a permanent binding
   (`packages/schedules`' consent sweep already treats "delivered export" as the durable
   abstraction, vendor interchangeable); naming the package for the grain it ingests, not the
   vendor, avoids a rename if the source ever changes while the `{subject_key}:{channel}` grain
   does not.
2. **Reader: `RowSource` protocol + pinned contract + `pulse_core.cursor`, verdict-relay's shape
   verbatim.** `CONTRACT_COLUMNS` pins the landing row's required fields — `subject_key`,
   `channel`, `to_state`, a message/event identifier for provenance, and an orderable event
   timestamp the cursor pages on (mirroring `computed_at`) — validated per row, with the
   **catch-and-collect shape of `consent_sweep.parse_export`, not `mart_reader._validated`'s
   raise-and-abort** (*corrected at G_MECE:* Requirement 5 pins malformed rows as counted and
   attached, never dropped, with the remaining rows still declared — an aborting validator
   would contradict this change's own spec; mart_reader's shape is right for the verdict mart,
   whose contract makes a malformed row run-ending, and wrong here). Row errors name the row by
   position and column, never by contact value. *Alternative
   considered:* read `cio_raw` and `cio_prod` through two separate readers. Rejected for v1 — the
   proposal and ADR-0005 treat the landing as one consumed surface; if `cio_raw` (unmodeled) and
   `cio_prod` (modeled) diverge enough to need separate contracts, that is a schema question for
   `docs/contracts/consumes.md` to pin precisely, not a reason to fork the reader shape before a
   real drift is observed.
3. **Grain composition, D9 authority, and no-PHI receipt shape are inherited from
   `consent_sweep.py`, not redesigned.** The declarer composes `f"{subject_key}:{channel}"`
   identically, and its receipt reports counts and identifying references only — this is the
   binding contract `consent-reconciliation`'s spec already states; the sweep is not consulted at
   runtime, only its composition function's shape is duplicated (no new intra-package dependency
   between `schedules` and `consent-ingress` — each stays a standalone workspace member, same as
   `verdict-relay` and `schedules` today).
4. **D16 `logical_time` derives from the landing row's own event identity, never wall-clock.**
   Concretely, the row's event timestamp (the field the cursor also pages on) plus its
   message/event id folds into the command payload as provenance, so
   `derive_idempotency_key`'s payload-hash already changes if two distinct events for the same
   (subject, channel) land — re-declaring the *same* row, whether via a cursor-resume re-read or a
   full re-run with no new landing, produces the identical key and classifies `replayed`, the
   `verdict_relay`/`schedules` re-runnability posture applied to this ingress's own input shape.
5. **No producer-policy suppression entry, no gate-coverage change.** Documented above (Context)
   so the "must stay green under producer-policy" constraint is traceable: the gate's scope is
   `packages/ocean`; this package emits nothing there is a vocabulary to classify. If a future
   change moves consent-ingress logic into `packages/ocean` (it should not, per Decision 1), that
   move would need its own producer-policy review at that time.
6. **Tests fake at one boundary: the `RowSource`.** No live network, `--disable-socket`,
   fixture-backed rows in every test — the identical posture `mart_reader`'s test suite already
   proves out. The command-API client is faked at the same boundary `consent_sweep`'s and
   `verdict_relay.declarer`'s tests already use (a scripted `PulseCoreClient` substitute).

## Risks / Trade-offs

- **[`cio_raw`/`cio_prod` schema drift]** → the reader's contract validation rejects the row
  before any declaration, naming it in the receipt. Mitigation: `docs/contracts/consumes.md`
  pins the row contract this reader validates against, so drift is a diffable doc change, not a
  silent surprise; same posture as the verdict mart entry already in that doc.
- **[PHI: `cio_raw`/`cio_prod` carry contact identifiers upstream]** → receipts, logs, and every
  fixture in this package carry subject keys and channel names only. Mitigation: every exit path
  from row to receipt/log is covered by a no-PHI test (mirroring `consent_sweep`'s
  `ExportParseError`, which never carries a raw row); flagged for security review same as the
  sweep's receipt/logging paths were.
- **[Cursor/grain drift between this ingress and the reconciliation sweep]** → both derive from
  the same landing and the same `{subject_key}:{channel}` composition, so a disagreement is a
  query away rather than a systems question (per ADR-0005's own framing) — mitigated by the spec
  requirement that both paths compose the key identically, tested against the same composition
  function shape `consent_sweep.py` already pins.
- **[No live-pull freshness]** → accepted per ADR-0005: the export cadence bounds forward-ingress
  freshness; if that becomes insufficient, the named follow-on (live pull) is its own decision,
  not a silent scope creep of this change.

## Migration Plan

Pre-production, additive only: a new workspace member with no live schedule wired. Rollback is
removing the package; no data migration exists — declared commands are ordinary ledger commands,
subject to the same replay/rejection semantics as any other writer.
