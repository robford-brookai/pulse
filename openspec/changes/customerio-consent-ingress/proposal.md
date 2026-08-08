## Why

ADR-0005 (2026-08-08) cleared the last hold on Phase 2's final change: the DNA team and Tal
(compliance sign-off) confirmed Customer.io consent data joins the governed path, and the export
mechanism is settled — Snowflake database `streamline`, schemas `cio_raw`/`cio_prod`, no live
Customer.io API pull in v1. D9's forward consent ingress — actor `customer.io`, message-level
provenance — is the last of the phase's four sanctioned command sources; without it, consent data
reaching the ledger stays reconciliation-only (s13's sweep correcting drift after the fact) rather
than recorded at the source. This change proposes it now that the ADR unblocks it.

## What Changes

- **New package `packages/consent-ingress`**: a thin clock-driven reader/declarer with the same
  operational shape as `packages/verdict-relay` — cursor-based Snowflake reads at a `RowSource`
  boundary, pinned row contract, D16 idempotent command declaration — reading `streamline.cio_raw`
  and `cio_prod` instead of the verdict mart.
- **Forward consent declaration**: each landed consent row becomes one `record_communication_consent`
  command, actor `customer.io` via its own D15 per-service credential (attribution is
  authentication, never a payload field — ADR-0003), payload carrying message-level provenance
  (the source row's message/event id). Subject key composes as `{subject_key}:{channel}` — the
  exact composition `consent-reconciliation`'s sweep already uses, so the two paths can never
  disagree on which row a (subject, channel) pair owns.
- **D16 idempotency keyed off the landing row's own identity** (message id / row event time, never
  wall-clock), so re-reading the same landing rows on a cursor resume or a re-run replays rather
  than double-declaring.
- **No producer-policy exposure**: this package holds no catalog-state event vocabulary — it
  declares exclusively through the command API client boundary, the same posture
  `packages/schedules` and `packages/verdict-relay` already hold, so it needs nothing from the
  §4.4 ocean-source gate and introduces nothing for it to flag.
- **One CLI entrypoint** with `--dry-run`, mirroring `schedules`/`verdict-relay`: prints the
  would-declare set from a fixture `RowSource`, no client, no socket.
- **`docs/contracts/consumes.md`** gains an entry for `streamline.cio_raw`/`cio_prod`, pinning the
  row contract this ingress reads against, per the doc's own serial lane.
- Every Snowflake read is fixture-faked at the `RowSource` boundary in every test — no live
  network, `--disable-socket` — matching `mart_reader`'s tested posture.

## Capabilities

### New Capabilities

- `customerio-consent-ingress`: the D9 forward consent ingress — cursor-based `streamline.cio_raw`/
  `cio_prod` reads, the pinned row contract, the `{subject_key}:{channel}` grain composition
  shared with `consent-reconciliation`, `customer.io`-attributed `record_communication_consent`
  declaration with message-level provenance, D16 replay-on-reread idempotency, and the run
  receipt (declared / replayed / rejected / unparseable counts, subject keys and channel names
  only, never contact values).

### Modified Capabilities

_None._ `consent-reconciliation` already specifies the `{subject_key}:{channel}` composition as
binding on "any other producer of `communication_consent` state (e.g. a forward consent ingress)"
— this change is a new consumer of that pinned composition, not a change to its requirements.
`producer-policy` is unaffected: its gate scope is `packages/ocean` producer source, and this
package is not producer source under that gate — it is a command-API declarer, the same posture
already established by `packages/schedules` and `packages/verdict-relay`.

## Impact

- New package under `packages/` (`consent-ingress`), workspace member with the established
  conventions (uv, ruff, pyright/mypy, pytest, coverage floor 85, `--disable-socket`).
- Depends on S1.1 surfaces only: `pulse_core.client.PulseCoreClient.submit_command`,
  `pulse_core.idempotency.derive_idempotency_key`, `pulse_core.generated.RecordCommunicationConsentCommand`,
  and `pulse_core.cursor` (the same writer-state cursor facility `verdict_relay.mart_reader` uses).
  No new ledger endpoints, no schema changes.
- New external dependency: read access to Snowflake `streamline.cio_raw`/`cio_prod` — registered
  in `docs/contracts/consumes.md` by this change's doc task.
- Auth per D15: the ingress runs under its own `customer.io` service credential (name in config,
  value from the environment, never in code or fixtures); every declared command's actor resolves
  to `customer.io` because the client authenticates with that credential, not because any payload
  field names it (ADR-0003).
- Out of scope (named follow-on, per ADR-0005 alternatives): a live Customer.io API/webhook pull —
  v1 consumes only the delivered Snowflake export; freshness requirements outgrowing the export
  cadence would need its own decision.
- PHI: consent rows carry contact identifiers upstream in `cio_raw`/`cio_prod`; this ingress's
  logs, receipts, and test fixtures carry subject keys and channel names only, never contact
  values — every code path where a contact value could reach a log or leave the process is
  flagged and tested.
- Rollback: pre-production, additive only — no live schedule/trigger exists until wired outside
  this change (same posture as `s13-schedules`'s infra dir). Reverting is removing the package;
  no data migration exists.
