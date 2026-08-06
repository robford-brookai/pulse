"""`schedules.consent_sweep` parse and diff (task 3.1, spec: consent-reconciliation).

Fixtures under `fixtures/consent_sweep/` are the delivered Customer.io suppression export, CSV,
fixture-pinned format (design decision 5). The ledger side of the diff is faked at the
`enumerate_state` boundary (design decision 9) with `SubjectState` built directly — no Postgres
in this suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pulse_ledger.reads import SubjectState
from schedules.consent_sweep import (
    Correction,
    CorrectionDirection,
    ExportHeaderError,
    diff_consent,
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
