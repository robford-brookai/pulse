"""The consent grain's cross-package parity gate: ingress and sweep compose one key identically.

`consent-reconciliation`'s spec makes `f"{subject_key}:{channel}"` binding for the
`communication_consent` grain, and two packages compose it independently — `schedules.consent_sweep`
(the correcting sweep) and `consent_ingress.declarer` (D9's forward ingress). Neither depends on the
other at runtime: the composition is duplicated, not imported (customerio-consent-ingress design
decision 3), so each stays a standalone workspace member.

Duplication is the decision; silent divergence is the risk it carries. This repo-level test is where
that risk is paid for — it is the only place both packages are importable, and it calls both
composition functions on the same inputs rather than comparing either against a pinned string. A
change to one composition that is not made to the other turns this red, which is exactly the
"ingress and sweep can never disagree on which row a (subject, channel) pair owns" invariant both
specs state.

Offline: pure function calls, no network, no credentials, no fixtures beyond synthetic keys.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from consent_ingress.declarer import build_record_communication_consent_command
from consent_ingress.declarer import ledger_subject_key as ingress_key
from consent_ingress.row_source import ConsentRow, ConsentRowReader, FixtureRowSource
from schedules.consent_sweep import SUBJECT_TYPE as SWEEP_SUBJECT_TYPE
from schedules.consent_sweep import (
    Correction,
    CorrectionDirection,
    ExportRow,
)
from schedules.consent_sweep import _ledger_key as sweep_key
from schedules.consent_sweep import (
    build_record_communication_consent_command as build_sweep_command,
)

#: Synthetic (subject, channel) pairs spanning the object model's three channels plus the shapes a
#: naive composition could disagree on: a key containing the separator, and an empty-ish channel.
_PAIRS = (
    ("SUBJ-001", "email"),
    ("SUBJ-002", "sms"),
    ("SUBJ-003", "voice"),
    ("SUBJ-004:legacy", "email"),
    ("SUBJ-005", "email:transactional"),
)


@pytest.mark.parametrize(("subject_key", "channel"), _PAIRS)
def test_ingress_and_sweep_compose_the_same_ledger_key(subject_key: str, channel: str):
    """Both compositions, called on the same pair, return the same `current_state` row key."""
    assert ingress_key(subject_key, channel) == sweep_key(subject_key, channel)
    assert ingress_key(subject_key, channel) == f"{subject_key}:{channel}"


def test_both_paths_address_one_row_with_the_same_subject_type_and_key():
    """The full addressing tuple, not just the key: a `record_communication_consent` command built
    by either path for the same (subject, channel) pair addresses the identical ledger row."""
    subject_key, channel = "SUBJ-006", "sms"
    reader = ConsentRowReader(
        FixtureRowSource([
            {
                "subject_key": subject_key,
                "channel": channel,
                "to_state": "opted_out",
                "message_id": "cio-msg-0006",
                "event_time": "2026-08-01T12:00:00+00:00",
            }
        ]),
        _NullCursorStore(),
    )
    (page,) = list(reader.batches())
    (row,) = page.rows

    ingress_command = build_record_communication_consent_command(row)
    sweep_command = build_sweep_command(
        Correction(
            subject_key=subject_key,
            channel=channel,
            direction=CorrectionDirection.OPT_OUT,
            export_row=ExportRow(row_number=1, subject_key=subject_key, channel=channel, suppressed=True),
        ),
        file_id="export-42",
    )

    assert ingress_command.subject_type == sweep_command.subject_type == SWEEP_SUBJECT_TYPE
    assert ingress_command.subject_key == sweep_command.subject_key == f"{subject_key}:{channel}"
    assert ingress_command.command_type == sweep_command.command_type == "record_communication_consent"
    assert ingress_command.channel == sweep_command.channel == channel


def test_the_two_paths_carry_their_own_provenance_not_each_others():
    """Same row, different authority: the sweep's provenance is an export row reference, the
    ingress's is a landing message id. Identical addressing must not mean identical evidence."""
    row = ConsentRow(
        subject_key="SUBJ-007",
        channel="email",
        to_state="opted_in",
        message_id="cio-msg-0007",
        event_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    ingress_command = build_record_communication_consent_command(row)

    assert ingress_command.evidence_ref == "cio:message:cio-msg-0007"
    assert "row:" not in str(ingress_command.evidence_ref)


class _NullCursorStore:
    """A never-checkpointed cursor store — paging is task 2.1's contract, not this gate's."""

    def load(self) -> None:
        return None

    def save(self, cursor: object) -> None:  # pragma: no cover - never reached, no commit() here
        msg = f"this gate never commits a cursor, got {cursor!r}"
        raise AssertionError(msg)
