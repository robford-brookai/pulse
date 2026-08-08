"""Declare validated landing rows as `record_communication_consent` commands (task 3.1).

The forward half of D9's consent story: `row_source` produces validated `ConsentRow`s, this module
turns each into exactly one command on the ledger's single write path. Four things are load-bearing
here, and each is a contract this module shares with something outside it:

- **The grain composition.** `CommunicationConsent` is per patient x channel, but the ledger's
  `current_state` keys one row per `(subject_type, subject_key)` — a single string. This module
  composes that string as `f"{subject_key}:{channel}"`, which is not a local choice:
  `openspec/specs/consent-reconciliation` makes it binding, and `schedules.consent_sweep._ledger_key`
  composes the identical string for the correcting sweep. The two paths read and write the same
  landing, so a divergence here would have them silently disagree about which ledger row a
  (subject, channel) pair owns. The sweep is *not* imported — the composition is duplicated by
  design (customerio-consent-ingress design decision 3: `schedules` and `consent-ingress` each stay
  a standalone workspace member with no dependency on the other) — and the duplication is paid for
  by `tests/test_consent_grain_parity.py` at the repo root, which calls both compositions on the
  same inputs and fails if they ever part ways.

- **Attribution is authentication (ADR-0003).** Every command's actor becomes `customer.io` because
  `client` authenticates with this ingress's own D15 credential, whose name `CUSTOMERIO_WRITER_ID`
  pins — never because this module writes an actor field, which it does not, anywhere. The
  credential's token value lives in the environment and reaches `PulseCoreClient` at the CLI
  boundary (task 4.1); only the name belongs in source.

- **Provenance.** Each payload carries `landing_row_reference(row)` — the source row's Customer.io
  message id — so a recorded consent state traces back to the message that produced it. A message id
  is not a contact value: no email address, phone number, or other `cio_raw`/`cio_prod` contact
  field ever reaches a command, a receipt, or a log line.

- **`effective_at` comes from the row, never the wall clock.** It doubles as the D16 idempotency
  key's `logical_time` (`pulse_core.client.submit_command`), so deriving it from the row's own event
  time is what makes a re-read of the same landing row reproduce the same key and classify
  `replayed`. Task 3.2 owns proving that across both re-read paths (a cursor resume and a full
  re-run); this module's part of it is only that it reads no clock.

`PulseCoreClient` is the single exit: this module holds no HTTP client, no warehouse connection, and
no bus publish of its own, and emits no catalog-state event as a producer (the ingress has no
catalog-state event vocabulary — spec Requirement 1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pulse_core.client import CommandResponse, PulseCoreClient
from pulse_core.generated import RecordCommunicationConsentCommand

from consent_ingress.row_source import ConsentRow

#: D15: this ingress's own service credential name. A per-writer bearer credential resolves to
#: `writer_id` = actor server-side (ADR-0003), so authenticating `client` with the credential named
#: `customer.io` is what makes every declared command's actor `customer.io`. Distinct from
#: `row_source.CURSOR_WRITER_ID`, which scopes the durable cursor, not command attribution. The
#: token value comes from the environment; only the name is pinned here.
CUSTOMERIO_WRITER_ID = "customer.io"

#: Namespace for the provenance reference each payload carries, so a bare message id can never be
#: mistaken for another authority's row reference (the sweep's is `{file_id}:row:{n}`).
LANDING_REFERENCE_PREFIX = "cio:message"


def ledger_subject_key(subject_key: str, channel: str) -> str:
    """The `current_state` row key for one (subject, channel) `communication_consent` grain.

    Binding, not local: `openspec/specs/consent-reconciliation` pins this composition and
    `schedules.consent_sweep._ledger_key` must produce the identical string for the same pair. Edit
    one and `tests/test_consent_grain_parity.py` fails until the other agrees.
    """
    return f"{subject_key}:{channel}"


def landing_row_reference(row: ConsentRow) -> str:
    """The provenance a declaration's payload carries: the landing row's message/event id.

    Carries the row's identity only — never a contact value from `cio_raw`/`cio_prod` (spec:
    "Receipts and logs carry no contact values"), so this reference is safe in a payload, a receipt
    (task 3.3), and a log line alike.
    """
    return f"{LANDING_REFERENCE_PREFIX}:{row.message_id}"


def build_record_communication_consent_command(row: ConsentRow) -> RecordCommunicationConsentCommand:
    """One landing row's `record_communication_consent` command, customer.io-attributed.

    `to_state` is the row's own recorded state, validated against the pinned row contract upstream
    (`row_source`) and against the catalog's `communication_consent` transitions server-side — this
    module neither reinterprets nor second-guesses what the landing says. No actor field: the
    credential supplies attribution (ADR-0003).
    """
    return RecordCommunicationConsentCommand(
        subject_key=ledger_subject_key(row.subject_key, row.channel),
        channel=row.channel,
        to_state=row.to_state,
        evidence_ref=landing_row_reference(row),
    )


@dataclass(frozen=True)
class ConsentDeclaration:
    """One row's command and the client's classified response.

    The run receipt (task 3.3) is a tally over these; this task returns them uninterpreted, paired
    with the row that produced each so the receipt never re-reads the landing to attribute one.
    """

    row: ConsentRow
    command: RecordCommunicationConsentCommand
    response: CommandResponse


def declare_consent_rows(rows: Sequence[ConsentRow], client: PulseCoreClient) -> list[ConsentDeclaration]:
    """Declare exactly one `record_communication_consent` command per validated landing row.

    `client` must authenticate with this ingress's own D15 credential (`CUSTOMERIO_WRITER_ID`) so the
    ledger resolves each command's actor to `customer.io` — attribution is authentication (ADR-0003),
    never a payload field this function could set instead. Declarations happen in `rows`' own order,
    the reader's read order (ascending event time).

    `effective_at` is the row's own `event_time`, the same field the cursor pages on — the D16
    `logical_time` (design decision 4), read from the row rather than a clock so re-reading the same
    row reproduces the same idempotency key. Responses come back uninterpreted: a `rejected` or
    `transient` classification is the receipt's to tally and the CLI's to exit nonzero on (tasks 3.3,
    4.1), not this function's to raise on — one bad row must not abort the rest of a page.
    """
    declarations: list[ConsentDeclaration] = []
    for row in rows:
        command = build_record_communication_consent_command(row)
        response = client.submit_command(command, effective_at=row.event_time)
        declarations.append(ConsentDeclaration(row=row, command=command, response=response))
    return declarations
