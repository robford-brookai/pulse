# Synthetic Twenty webhook payloads

Fixed, hand-authored `record.updated`/`record.created`/`record.deleted` bodies, pinned from
Twenty's documented webhook shape plus `design/platform/twenty-data-model.md`'s PatientProgram /
Patient objects (the `twenty-kanban-webhook-ingress` design.md Context section names both). No
live Twenty instance exists until Phase 3 (`environment-matrix`), so every downstream test signs
and replays these bytes rather than recording a live capture; the Phase 3 task on
`pulse-app-scaffold`'s ladder re-verifies the shape live before production enablement.

Load fixtures through `tests/twenty_fixtures.py`, never by hand-opening a path — it is the one
place the filename → case mapping and the signature helper live.

## PHI posture

Every record carries a first name of `Canary` and a case-specific last name (`LegalDrag`,
`IllegalDrag`, ...) — synthetic, obviously fake, and unique enough per case that a caplog / receipt
/ comment-body grep for `Canary` catches a leak from any one of them. `malformed_body.json` carries
the same convention *inside its unparseable bytes*, deliberately: a handler that naively logs a
body it failed to `json.loads` is exactly the leak this fixture exists to catch.

## Cases

| File | `eventType` | Object | Disposition it should drive | Notes |
|---|---|---|---|---|
| `legal_drag.json` | `record.updated` | `patientProgram` | committed | `lifecycleStatus` `registered` → `enrolled`; canonical spine ID and workspace member present. |
| `illegal_drag.json` | `record.updated` | `patientProgram` | rejected | `lifecycleStatus` `activated` → `registered` — backwards, not a legal transition. |
| `redelivery_duplicate.json` | `record.updated` | `patientProgram` | replayed | Byte-identical to `legal_drag.json`, same `eventId` — Twenty's at-least-once redelivery of a drag that already committed (D16). |
| `missing_canonical_id.json` | `record.updated` | `patientProgram` | unmapped | A mapped status-field drag whose `patient` carries no `canonicalPatientId` — refused, never guessed from the Twenty record ID. |
| `noop_create.json` | `record.created` | `patientProgram` | no-op | Record creation, not an update — no `updatedFields` to touch a status on. |
| `noop_delete.json` | `record.deleted` | `patientProgram` | no-op | Record deletion. |
| `noop_non_status_update.json` | `record.updated` | `patientProgram` | no-op | `updatedFields` touches `qualificationStatus`, not the mapped board's `lifecycleStatus`. |
| `noop_unmapped_object.json` | `record.updated` | `provider` | no-op | A status change on an object the v1 board mapping does not cover at all. |
| `malformed_body.txt` | — | — | 422, no processing | Not valid JSON — a truncated body, signed and posted as raw bytes. `.txt`, not `.json`, so pre-commit's JSON hooks don't reject the deliberately-broken content. |

## `eventId` and idempotency

`eventId` is Twenty's webhook delivery id, the D16 idempotency key's logical time
(`pulse_core.idempotency.derive_idempotency_key`, `twenty-kanban-webhook-ingress` design decision
4). `redelivery_duplicate.json` shares `legal_drag.json`'s `eventId` on purpose: two deliveries of
the same notification must derive the same key and commit exactly one event between them.

## Canonical identifiers, never the Twenty record ID

Every `record.id` and every nested object's `id` (`patient.id`, `program.id`, the top-level
`record.id` itself) is a synthetic Twenty-internal identifier — never a subject key. The canonical
identity a mapped drag resolves against is `patient.canonicalPatientId` (the `DIM_PATIENT_CONFORMED`
spine ID per `twenty-data-model.md`); `program.code` is the envelope's `program` field
(`event-envelope-spec.md`). `missing_canonical_id.json` is the one fixture where
`canonicalPatientId` is absent entirely, not merely blank.

## Signing

`tests/twenty_fixtures.py`'s `sign_fixture` wraps `pulse_ledger.auth.sign` so no test hand-rolls
the HMAC recipe. It signs the fixture's raw bytes exactly as loaded — re-serializing a parsed dict
and signing that would sign a body Twenty never actually sent, since JSON key order and whitespace
are not preserved by a parse/dump round trip.
