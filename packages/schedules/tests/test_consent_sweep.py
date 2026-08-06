"""`schedules.consent_sweep` parse and diff (task 3.1, spec: consent-reconciliation).

Fixtures under `fixtures/consent_sweep/` are the delivered Customer.io suppression export, CSV,
fixture-pinned format (design decision 5). The ledger side of the diff is faked at the
`enumerate_state` boundary (design decision 9) with `SubjectState` built directly — no Postgres
in this suite.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import cast

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from pulse_ledger.reads import SubjectState
from schedules.consent_sweep import (
    RECONCILIATION_WRITER_ID,
    Correction,
    CorrectionDirection,
    ExportHeaderError,
    declare_consent_corrections,
    diff_consent,
    export_logical_time,
    export_row_reference,
    parse_export,
)

FIXTURES = Path(__file__).parent / "fixtures" / "consent_sweep"


def _ledger_state(subject_key: str, channel: str, state: str) -> SubjectState:
    """A recorded `communication_consent` current-state row, as `enumerate_state` would return."""
    return SubjectState(
        subject_type="communication_consent",
        subject_key=f"{subject_key}:{channel}",
        state=state,
        effective_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        last_event_id=uuid.uuid4(),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def test_parses_the_fixture_pinned_csv_format():
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())

    assert result.errors == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.row_number == 1
    assert row.subject_key == "SUBJ-001"
    assert row.channel == "sms"
    assert row.suppressed is True


def test_opt_out_missing_from_the_ledger():
    """spec: "Opt-out missing from the ledger" — export row suppressing a subject the ledger
    shows as consented → an opt-out correction is declared for that subject."""
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())
    ledger_states = [_ledger_state("SUBJ-001", "sms", "opted_in")]

    corrections = diff_consent(result.rows, ledger_states)

    assert corrections == [
        Correction(
            subject_key="SUBJ-001",
            channel="sms",
            direction=CorrectionDirection.OPT_OUT,
            export_row=result.rows[0],
        )
    ]


def test_opt_out_missing_from_the_ledger_when_no_row_exists():
    """No current-state row at all (the ledger's "unset" — no transition has ever recorded this
    subject/channel) is the same disagreement as an explicit opted_in row."""
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())

    corrections = diff_consent(result.rows, ledger_states=[])

    assert corrections == [
        Correction(
            subject_key="SUBJ-001",
            channel="sms",
            direction=CorrectionDirection.OPT_OUT,
            export_row=result.rows[0],
        )
    ]


def test_ledger_opt_out_the_export_contradicts():
    """spec: "Ledger opt-out the export contradicts" — a subject the ledger shows as opted out
    and the export shows as not suppressed → an opt-in correction is declared for that subject."""
    result = parse_export((FIXTURES / "opt_in_drift.csv").read_text())
    ledger_states = [_ledger_state("SUBJ-002", "email", "opted_out")]

    corrections = diff_consent(result.rows, ledger_states)

    assert corrections == [
        Correction(
            subject_key="SUBJ-002",
            channel="email",
            direction=CorrectionDirection.OPT_IN,
            export_row=result.rows[0],
        )
    ]


def test_agreement_produces_no_correction():
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())
    ledger_states = [_ledger_state("SUBJ-001", "sms", "opted_out")]

    assert diff_consent(result.rows, ledger_states) == []


def test_ledger_states_for_other_subject_types_are_ignored():
    """`enumerate_state` is typed to `communication_consent` by its caller, but the diff does not
    trust that — a row of another subject type sharing the composed key string must never match."""
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())
    other_type_state = SubjectState(
        subject_type="referral",
        subject_key="SUBJ-001:sms",
        state="received",
        effective_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        last_event_id=uuid.uuid4(),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    corrections = diff_consent(result.rows, [other_type_state])

    assert corrections == [
        Correction(
            subject_key="SUBJ-001",
            channel="sms",
            direction=CorrectionDirection.OPT_OUT,
            export_row=result.rows[0],
        )
    ]


def test_missing_required_column_raises():
    with pytest.raises(ExportHeaderError):
        parse_export("subject_key,channel\nSUBJ-001,sms\n")


def test_unrecognised_boolean_value_is_a_row_error_not_a_crash():
    result = parse_export("subject_key,channel,suppressed\nSUBJ-003,sms,maybe\n")

    assert result.rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 1


# --- task 3.2: declaration (attribution, provenance, replay) ---


def committed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(201, json={"event_id": event_id, "replayed": False})


def replayed(event_id: str = "e1") -> httpx.Response:
    return httpx.Response(200, json={"event_id": event_id, "replayed": True})


class ScriptedApi:
    """The command API faked at the client boundary: scripted answers, recorded request bodies.

    `writer_id` defaults to the sweep's own D15 credential name — `client()` stands in for what
    the CLI boundary would build from config (the name) plus the environment (the token value).
    """

    def __init__(self, responses: list[httpx.Response], *, writer_id: str = RECONCILIATION_WRITER_ID) -> None:
        self.bodies: list[dict[str, object]] = []
        self._responses = responses
        self._writer_id = writer_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed = json.loads(request.content)
        assert isinstance(parsed, dict)
        self.bodies.append(cast("dict[str, object]", parsed))
        return self._responses[min(len(self.bodies), len(self._responses)) - 1]

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id=self._writer_id,
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


def test_export_row_reference_is_file_id_and_row_number():
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())

    assert export_row_reference("export-42", result.rows[0]) == "export-42:row:1"


def test_export_logical_time_has_no_wall_clock_component():
    assert export_logical_time(date(2026, 8, 5)) == datetime(2026, 8, 5, tzinfo=timezone.utc)


def test_a_correction_is_attributed_and_traceable():
    """spec: "A correction is attributed and traceable" — the command's actor is `reconciliation`
    and its payload references the export row, and re-running the sweep on the same export
    classifies the same correction as `replayed`.

    Attribution is authentication (ADR-0003): no actor field travels in the body, so the actor
    assertion is that `client` authenticates with the `reconciliation` credential — observable
    here via the D16 idempotency key, which is always `{writer_id}:{digest}`.
    """
    result = parse_export((FIXTURES / "opt_out_drift.csv").read_text())
    corrections = diff_consent(result.rows, ledger_states=[])
    export_as_of = date(2026, 8, 5)

    first_api = ScriptedApi([committed()])
    first = declare_consent_corrections(corrections, first_api.client(), file_id="export-42", export_as_of=export_as_of)

    assert len(first) == 1
    first_body = first_api.bodies[0]
    assert str(first_body["idempotency_key"]).startswith(f"{RECONCILIATION_WRITER_ID}:")
    assert cast("dict[str, object]", first_body["payload"])["evidence_ref"] == "export-42:row:1"
    assert first[0].response.classification.value == "committed"

    second_api = ScriptedApi([replayed()])
    second = declare_consent_corrections(
        corrections, second_api.client(), file_id="export-42", export_as_of=export_as_of
    )

    assert second[0].response.classification.value == "replayed"
    assert second_api.bodies[0]["idempotency_key"] == first_body["idempotency_key"]


def test_opt_in_correction_declares_the_opposite_to_state():
    result = parse_export((FIXTURES / "opt_in_drift.csv").read_text())
    ledger_states = [
        SubjectState(
            subject_type="communication_consent",
            subject_key="SUBJ-002:email",
            state="opted_out",
            effective_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            last_event_id=uuid.uuid4(),
            updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
    ]
    corrections = diff_consent(result.rows, ledger_states)
    api = ScriptedApi([committed()])

    declarations = declare_consent_corrections(
        corrections, api.client(), file_id="export-42", export_as_of=date(2026, 8, 5)
    )

    assert declarations[0].command.to_state == "opted_in"
    assert declarations[0].command.subject_key == "SUBJ-002:email"
    assert cast("dict[str, object]", api.bodies[0]["payload"])["evidence_ref"] == "export-42:row:1"
