"""Regenerate the canonical request v1 golden vectors. Run from the repo root."""

import json
from pathlib import Path

from pulse_ledger.api import WEBHOOK_WRITER, declaration_from_request
from pulse_ledger.auth import BACKFILL_ACTOR_ID, Writer
from pulse_ledger.request_fingerprint import FINGERPRINT_VERSION, request_fingerprint

CONNECTOR = Writer(writer_id="clinic-connector", actor_authority="connector")
PRINCIPALS = {
    "bearer": CONNECTOR,
    "batch": Writer(writer_id=BACKFILL_ACTOR_ID, actor_authority="backfill"),
    "webhook": WEBHOOK_WRITER,
}
SUBJECT_KEY = "enrollment-synthetic-0001"


def body(**overrides):
    request = {
        "subject_type": "enrollment",
        "subject_key": SUBJECT_KEY,
        "event_type": "declare_transition",
        "to_state": "on_hold",
        "effective_at": "2026-08-03T11:59:00+00:00",
        "payload": {"hold_reason": "awaiting_authorization"},
    }
    request.update(overrides)
    return request


CASES = [
    ("baseline", "bearer", "utc_alias", "The reference request: explicit +00:00, one payload member.", body()),
    (
        "utc_alias_zulu",
        "bearer",
        "utc_alias",
        "Trailing Z is the same instant as +00:00.",
        body(effective_at="2026-08-03T11:59:00Z"),
    ),
    (
        "utc_alias_offset",
        "bearer",
        "utc_alias",
        "A +02:00 wall clock naming the same instant.",
        body(effective_at="2026-08-03T13:59:00+02:00"),
    ),
    (
        "key_order_declared",
        "bearer",
        "key_order",
        "Payload members in one order.",
        body(payload={"hold_reason": "awaiting_authorization", "note": "reordered"}),
    ),
    (
        "key_order_swapped",
        "bearer",
        "key_order",
        "The same payload members, built in the other order.",
        body(payload={"note": "reordered", "hold_reason": "awaiting_authorization"}),
    ),
    (
        "list_order_declared",
        "bearer",
        "list_order",
        "A list of codes as the writer sent them.",
        body(payload={"codes": ["A", "B"]}),
    ),
    (
        "list_order_reversed",
        "bearer",
        "list_order",
        "The same codes reversed — a different request.",
        body(payload={"codes": ["B", "A"]}),
    ),
    (
        "payload_value_changed",
        "bearer",
        "payload_change",
        "One payload value differs from the baseline.",
        body(payload={"hold_reason": "awaiting_records"}),
    ),
    (
        "evidence_added",
        "bearer",
        "evidence_change",
        "The baseline request plus evidence.",
        body(evidence={"source_document": "synthetic-fax-0001"}),
    ),
    (
        "evidence_bounds_widened",
        "bearer",
        "evidence_change",
        "Evidence bounds are part of the accepted request.",
        body(
            evidence={"source_document": "synthetic-fax-0001"},
            evidence_bounds=["2026-08-01T00:00:00+00:00", "2026-08-02T00:00:00+00:00"],
        ),
    ),
    (
        "batch_principal",
        "batch",
        "batch_principal",
        "Baseline bytes under the batch credential: one request, another claimant.",
        body(),
    ),
    (
        "webhook_principal",
        "webhook",
        "webhook_principal",
        "Baseline bytes under the fixed signed-Twenty principal.",
        body(),
    ),
]

vectors = []
for name, principal, covers, note, request in CASES:
    declaration = declaration_from_request(dict(request), PRINCIPALS[principal])
    vectors.append({
        "name": name,
        "principal": principal,
        "covers": covers,
        "note": note,
        "request": request,
        "fingerprint": request_fingerprint(declaration),
    })

document = {
    "fingerprint_version": FINGERPRINT_VERSION,
    "note": (
        "Golden vectors for canonical request v1 (idempotency-integrity 1.1). Synthetic data only. "
        "Regenerate with scripts/regen_request_fingerprint_golden.py, and only alongside a new "
        "fingerprint version — a changed digest here re-keys every deployed producer's retries."
    ),
    "vectors": vectors,
}
Path("packages/pulse-ledger/tests/fixtures/request_fingerprint_v1_golden.json").write_text(
    json.dumps(document, indent=2, sort_keys=False) + "\n"
)
print("wrote", len(vectors), "vectors")
