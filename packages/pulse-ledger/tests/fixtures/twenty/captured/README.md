# Captured Twenty webhook deliveries — the artifact that retires the pin

Two real `patientProgram.updated` deliveries captured from the live dev instance
(`twenty-dev.cloud.brook.ai`, `twentycrm/twenty:v2.30.0`) on 2026-08-17, task 4.2 of
`twenty-dev-instance`. Everything here is synthetic seed data — no PHI, and the record carries
only pseudonymous identifiers (`canonicalPatientId`, `programCode`) plus Twenty's own ids.

Bodies are stored as `.body.raw`, **never `.json`** — they are the exact bytes the signature
covers, and the repo's `pretty-format-json` hook would silently rewrite (and invalidate) a
`.json` body. Verify against these bytes as-read; never against a reserialization. Signatures are **re-signed with the documented test
secret** in each `.meta.json`; the live dev secret's signature is not committed (its first
eight hex characters are recorded as provenance so a future capture can be matched).

## What these prove

**Signing** — verified by recomputation against the live secret before re-signing:
`HMAC-SHA256(secret, f"{timestamp}:" + raw_body_bytes)`, hex digest, **no version affixes**,
timestamp in **milliseconds**. `auth.py`'s `"v1="` / `"v1:{ts}:"` format and its seconds-based
freshness window are both wrong, and the millisecond mismatch alone fails every delivery.

**Envelope** — `eventName: "patientProgram.updated"` (not `eventType: "record.updated"`);
`updatedFields` is a **string array** (`["lifecycleStatus"]`), with values read from the flat
`record`; there is **no per-delivery event id**; `workspaceMemberId` is nested inside
`createdBy`/`updatedBy` and is `null` for an API-sourced write.

**Flat record** — `record` carries `canonicalPatientId` and `programCode` directly (the
denormalized columns added for exactly this reason), so subject resolution needs no read-back.

**Effective time (F3) — confirmed live.** In both deliveries `lifecycleStatusAsOf` stays
`2026-08-03T09:00:00.000Z` while `lifecycleStatus` changes and `record.updatedAt` advances. A
status change stamps **no** as-of field, so `effective_at` must derive from `record.updatedAt`
or the delivery must be refused — inheriting the previous projection's timestamp would be a
silent wrong `effective_at`.

**Idempotency source (D16).** Two genuine drags on the same record produce distinct
`record.updatedAt` values (`04:12:25.725Z` then `04:18:18.371Z`), so it distinguishes a real
re-drag from a replay. **Twenty v2.30 did not retry** the first delivery despite a 500 response
and a >15-minute wait, so no redelivery pair could be captured; treat "a retry re-signs with a
fresh timestamp" as still unobserved rather than assumed.
