# Synthetic Twenty webhook payloads

Fixed synthetic bodies in the envelope shape Twenty v2.30 actually sends, re-cut (task 5.2 of
`twenty-dev-instance`) from the two real deliveries in `captured/` — read that directory's README
for what was observed and how it was verified. These files are *cases*, not captures: each one
bends the captured shape along exactly one axis (illegal move, missing canonical id, CRUD noise,
truncated bytes) so a downstream suite can drive one disposition per file.

Load fixtures through `tests/twenty_fixtures.py`, never by hand-opening a path — it is the one
place the filename → case mapping and the signature helper live.

## The captured envelope shape, in brief

- The event discriminator is `eventName` (`patientProgram.updated`), not a bare `eventType`.
- `updatedFields` is a **string array of field names**; new values are read from the flat
  `record`. There is no per-field before/after pair.
- `record` is the flat ORM entity: `canonicalPatientId` and `programCode` are scalar fields on
  the record itself (the denormalized columns), and `workspaceMemberId` sits nested inside
  `createdBy`/`updatedBy` — `null` for an API-sourced write, populated for a UI (`MANUAL`) one.
- There is **no per-delivery event id**: `webhookId` is per-webhook, `eventDate` per-batch. The
  idempotency source is `record.updatedAt` (D16), and `effective_at` derives from it too (F3) —
  a UI drag stamps no as-of field, so `lifecycleStatusAsOf` stays stale across a drag.
- SELECT values arrive UPPER_SNAKE on the wire (`ACTIVE`, `PENDING_START`); the catalog vocabulary
  is lowercase (`active`, `pending_start`). `pulse_core.twenty_validate.encode_option_value` is
  the one encoding convention for that boundary.

## PHI posture

Every record's `name` (the card title Twenty stores on the row) is `Canary <Case>` —
synthetic, obviously fake, and unique per case so a caplog / receipt / comment-body grep for
`Canary` catches a leak from any one of them. `updatedBy.name` carries `Canary CareCoordinator`
for the UI-sourced writes. `malformed_body.txt` carries the same convention *inside its
unparseable bytes*, deliberately: a handler that naively logs a body it failed to `json.loads`
is exactly the leak this fixture exists to catch.

## Cases

| File | `eventName` | Disposition it should drive | Notes |
|---|---|---|---|
| `legal_drag.json` | `patientProgram.updated` | committed | `lifecycleStatus` → `ACTIVE` (catalog `pending_start` → `active`); canonical id and `updatedBy.workspaceMemberId` present. |
| `illegal_drag.json` | `patientProgram.updated` | rejected | `lifecycleStatus` → `PENDING_START` while the subject sits in `active` — backwards, not a legal transition. |
| `redelivery_duplicate.json` | `patientProgram.updated` | replayed | Byte-identical to `legal_drag.json`, same `record.updatedAt` — a redelivery of a drag that already committed (D16). |
| `missing_canonical_id.json` | `patientProgram.updated` | unmapped | A mapped status-field drag whose flat record carries no `canonicalPatientId` — refused, never guessed from the Twenty record ID. |
| `noop_create.json` | `patientProgram.created` | no-op | Record creation — the event name does not end `.updated`, and there is no `updatedFields`. |
| `noop_delete.json` | `patientProgram.deleted` | no-op | Record deletion. |
| `noop_non_status_update.json` | `patientProgram.updated` | no-op | `updatedFields` names `qualificationStatus`, not the mapped board's `lifecycleStatus`. |
| `noop_unmapped_object.json` | `provider.updated` | no-op | A status change on an object the v1 board mapping does not cover at all. |
| `malformed_body.txt` | — | malformed, acknowledged | Not valid JSON — a truncated body, signed and posted as raw bytes. `.txt`, not `.json`, so pre-commit's JSON hooks don't reject the deliberately-broken content. |

## Idempotency and effective time (D16, F3)

There is no delivery id, so `record.updatedAt` is both the D16 idempotency key's logical time and
the drag's `effective_at`. `redelivery_duplicate.json` shares `legal_drag.json`'s bytes on
purpose: two deliveries of one write carry the same `record.updatedAt` and must derive the same
key, while a genuine second drag advances `record.updatedAt` and is a new command. Twenty v2.30
was observed **not** retrying a delivery answered with 500, so redelivery signing is unobserved —
replay handling keys on `record.updatedAt` equality only, never on assumed retry behavior.

## Canonical identifiers, never the Twenty record ID

Every `record.id`, `programId`, and `patientId` is a synthetic Twenty-internal identifier — never
a subject key. The canonical identity a mapped drag resolves against is the flat
`canonicalPatientId` (the `DIM_PATIENT_CONFORMED` spine ID per `twenty-data-model.md`);
`programCode` is the envelope's `program` field (`event-envelope-spec.md`).
`missing_canonical_id.json` is the one patientProgram fixture where `canonicalPatientId` is
absent entirely, not merely blank.

## Signing

`tests/twenty_fixtures.py`'s `sign_fixture` wraps `pulse_ledger.auth.sign` so no test hand-rolls
the HMAC recipe. It signs the fixture's raw bytes exactly as loaded — re-serializing a parsed
dict and signing that would sign a body Twenty never actually sent, since JSON key order and
whitespace are not preserved by a parse/dump round trip.
