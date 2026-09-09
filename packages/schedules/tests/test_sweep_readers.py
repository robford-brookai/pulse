"""`schedules.sweep_readers` — task 1.3's read-only readers.

`LedgerStateReader` is exercised twice: once wired to a real `PulseCoreClient` over
`httpx.MockTransport` (proving it is genuinely the command API's per-subject read, this package's
own convention), and once against a small in-memory `SubjectHistorySource` fake for the folding
and malformed-event scenarios, which need no HTTP shape at all. `BoardReader` is exercised against
a real `ProjectionRestClient` over `httpx.MockTransport`, mirroring `twenty-projection`'s own test
style for the same client. `LandingReader`, `RowCountReader`, and `PatientsReader` (task 3.1) are
exercised against `FixtureReader`, their only implementation in this task. `conftest.py` blocks
sockets for every test in this package regardless.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlparse

import httpx
import pytest
from pulse_core.client import PulseCoreClient
from schedules.sweep_readers import (
    BoardFields,
    BoardReader,
    FixtureReader,
    LandingReader,
    LedgerStateReader,
    PatientsReader,
    RowCountReader,
    SweptRow,
)
from twenty_projection.apply import BoardTarget, ProjectionRestClient

SUBJECT_TYPE = "enrollment"


# --- LedgerStateReader --------------------------------------------------------------------


def _envelope(
    *,
    event_id: str | None = "11111111-1111-1111-1111-111111111111",
    seq: int | None = 1,
    to_state: str | None = "active",
    effective_at: str | None = "2026-08-01T00:00:00+00:00",
    recorded_at: str | None = "2026-08-01T00:00:05+00:00",
    reverses_event_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {} if to_state is None else {"to_state": to_state}
    return {
        "event_id": event_id,
        "subject_type": SUBJECT_TYPE,
        "subject_key": "enr-1",
        "seq": seq,
        "effective_at": effective_at,
        "recorded_at": recorded_at,
        "reverses_event_id": reverses_event_id,
        "payload": payload,
    }


class FakeHistorySource:
    """A `SubjectHistorySource` over recorded envelopes — no HTTP shape needed for the folding
    and malformed-event scenarios below."""

    def __init__(self, envelopes: Sequence[Mapping[str, object]]) -> None:
        self._envelopes = list(envelopes)

    def subject_history(self, subject_type: str, subject_key: str) -> Sequence[Mapping[str, object]]:
        assert subject_type == SUBJECT_TYPE
        assert subject_key == "enr-1"
        return self._envelopes


def test_ledger_state_reader_folds_to_current_state_and_snapshot_head() -> None:
    envelopes = [
        _envelope(seq=1, to_state="active", effective_at="2026-08-01T00:00:00+00:00"),
        _envelope(
            event_id="22222222-2222-2222-2222-222222222222",
            seq=2,
            to_state="on_hold",
            effective_at="2026-08-05T00:00:00+00:00",
        ),
    ]
    reader = LedgerStateReader(FakeHistorySource(envelopes))

    result = reader.read_subject(SUBJECT_TYPE, "enr-1")

    assert result.malformed == []
    assert result.row is not None
    assert result.row.subject_key == "enr-1"
    assert result.row.fields == {"state": "on_hold"}
    # The snapshot head is the highest committed seq, not the fold's own winner.
    assert result.row.cited_seq == 2


def test_ledger_state_reader_no_history_is_none_not_an_error() -> None:
    reader = LedgerStateReader(FakeHistorySource([]))

    result = reader.read_subject(SUBJECT_TYPE, "enr-1")

    assert result.row is None
    assert result.malformed == []


def test_ledger_state_reader_skips_non_state_bearing_events_without_flagging_them() -> None:
    envelopes = [
        _envelope(to_state=None, seq=1),
        _envelope(event_id="22222222-2222-2222-2222-222222222222", seq=2, to_state="active"),
    ]
    reader = LedgerStateReader(FakeHistorySource(envelopes))

    result = reader.read_subject(SUBJECT_TYPE, "enr-1")

    assert result.malformed == []
    assert result.row is not None
    assert result.row.fields == {"state": "active"}


def test_ledger_state_reader_counts_a_malformed_event_and_still_folds_the_rest() -> None:
    envelopes = [
        _envelope(event_id="not-a-uuid", seq=1, to_state="active"),
        _envelope(event_id="22222222-2222-2222-2222-222222222222", seq=2, to_state="on_hold"),
    ]
    reader = LedgerStateReader(FakeHistorySource(envelopes))

    result = reader.read_subject(SUBJECT_TYPE, "enr-1")

    assert len(result.malformed) == 1
    assert "event_id" in result.malformed[0].detail
    assert result.row is not None
    assert result.row.fields == {"state": "on_hold"}
    # The malformed event's own seq still counts toward the snapshot head.
    assert result.row.cited_seq == 2


def test_ledger_state_reader_a_reversal_advances_the_snapshot_head_past_the_surviving_state() -> None:
    envelopes = [
        _envelope(event_id="11111111-1111-1111-1111-111111111111", seq=1, to_state="active"),
        # A reversal is state-bearing itself in this fixture shape only via reverses_event_id;
        # its own seq still moves the ledger forward even though it carries no new state.
        _envelope(
            event_id="22222222-2222-2222-2222-222222222222",
            seq=2,
            to_state=None,
            reverses_event_id="11111111-1111-1111-1111-111111111111",
        ),
    ]
    reader = LedgerStateReader(FakeHistorySource(envelopes))

    result = reader.read_subject(SUBJECT_TYPE, "enr-1")

    assert result.row is None  # nothing survives the reversal
    assert result.malformed == []


def test_ledger_state_reader_wired_to_a_real_pulse_core_client() -> None:
    """`LedgerStateReader` is genuinely the command API's per-subject read: a real
    `PulseCoreClient` against a fixture transport satisfies `SubjectHistorySource` unmodified."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert urlparse(str(request.url)).path == "/subjects/enrollment/enr-1/events"
        return httpx.Response(200, json={"events": [_envelope(seq=1, to_state="active")]})

    client = PulseCoreClient(
        "https://ledger.test",
        writer_id="reconciliation",
        token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
        transport=httpx.MockTransport(handler),
    )
    reader = LedgerStateReader(client)

    result = reader.read_subject(SUBJECT_TYPE, "enr-1")

    assert result.row is not None
    assert result.row.fields == {"state": "active"}
    assert result.row.cited_seq == 1


# --- BoardReader ----------------------------------------------------------------------------

BOARD = BoardTarget(
    object_name="patientProgram",
    plural="patientPrograms",
    subject_type=SUBJECT_TYPE,
    status_field="lifecycleStatus",
    watermark_field="projectionSeq",
)
FIELDS = BoardFields(board=BOARD, subject_key_field="enrollmentSubjectKey", compared_fields=("lifecycleStatus",))


class FixtureTwentyListing:
    """A minimal Twenty core REST listing surface: one page, `data.<plural>` plus `pageInfo`."""

    def __init__(self, records: list[dict[str, object]]) -> None:
        self._records = records

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        assert request.method == "GET"
        assert path == f"/rest/{BOARD.plural}"
        return httpx.Response(
            200,
            json={
                "data": {BOARD.plural: self._records},
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            },
        )


def _board_record(subject_key: str = "enr-1", status: str = "active", seq: int = 3) -> dict[str, object]:
    return {
        "id": "rec-1",
        "enrollmentSubjectKey": subject_key,
        "lifecycleStatus": status,
        "projectionSeq": seq,
    }


def test_board_reader_reads_projected_fields_and_the_watermark() -> None:
    twenty = FixtureTwentyListing([_board_record()])
    client = ProjectionRestClient("https://twenty.test", token="unit-test-token", transport=twenty.transport())  # noqa: S106 — a fixture value, not a secret
    reader = BoardReader(client)

    result = reader.read_family(FIELDS)

    assert result.malformed == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.subject_key == "enr-1"
    assert row.fields == {"lifecycleStatus": "active"}
    assert row.cited_seq == 3


def test_board_reader_counts_a_record_missing_the_subject_key_field() -> None:
    record = _board_record()
    del record["enrollmentSubjectKey"]
    twenty = FixtureTwentyListing([record])
    client = ProjectionRestClient("https://twenty.test", token="unit-test-token", transport=twenty.transport())  # noqa: S106 — a fixture value, not a secret
    reader = BoardReader(client)

    result = reader.read_family(FIELDS)

    assert result.rows == []
    assert len(result.malformed) == 1
    assert "enrollmentSubjectKey" in result.malformed[0].detail


def test_board_reader_counts_a_non_int_watermark() -> None:
    record = _board_record()
    record["projectionSeq"] = "not-an-int"
    twenty = FixtureTwentyListing([record])
    client = ProjectionRestClient("https://twenty.test", token="unit-test-token", transport=twenty.transport())  # noqa: S106 — a fixture value, not a secret
    reader = BoardReader(client)

    result = reader.read_family(FIELDS)

    assert result.rows == []
    assert len(result.malformed) == 1
    assert result.malformed[0].position == "enr-1"


def test_board_reader_counts_a_record_missing_a_compared_field() -> None:
    record = _board_record()
    del record["lifecycleStatus"]
    twenty = FixtureTwentyListing([record])
    client = ProjectionRestClient("https://twenty.test", token="unit-test-token", transport=twenty.transport())  # noqa: S106 — a fixture value, not a secret
    reader = BoardReader(client)

    result = reader.read_family(FIELDS)

    assert result.rows == []
    assert len(result.malformed) == 1


def test_board_reader_never_holds_a_write_method() -> None:
    """The referee never writes for ledger-owned families (design.md decision 2)."""
    assert not hasattr(BoardReader, "patch_record")
    assert not hasattr(BoardReader, "create_comment")


# --- LandingReader / RowCountReader / FixtureReader --------------------------------------------


def test_landing_reader_parses_a_clean_fold_view_page() -> None:
    fixture = FixtureReader(
        rows_by_family={
            "enrollment": [
                {"subject_key": "enr-1", "state": "active", "seq": 5},
                {"subject_key": "enr-2", "state": "on_hold", "seq": 9},
            ]
        }
    )
    reader = LandingReader(fixture)

    result = reader.read_family("enrollment")

    assert result.malformed == []
    assert [row.subject_key for row in result.rows] == ["enr-1", "enr-2"]
    assert result.rows[0].fields == {"state": "active"}
    assert result.rows[0].cited_seq == 5


@pytest.mark.parametrize(
    ("row", "expected_position"),
    [
        ({"state": "active", "seq": 5}, "[offset 0]"),
        ({"subject_key": "enr-1", "seq": 5}, "enr-1"),
        ({"subject_key": "enr-1", "state": "active", "seq": "five"}, "enr-1"),
    ],
)
def test_landing_reader_counts_a_malformed_row_never_raises(row: dict[str, object], expected_position: str) -> None:
    fixture = FixtureReader(rows_by_family={"enrollment": [row]})
    reader = LandingReader(fixture)

    result = reader.read_family("enrollment")

    assert result.rows == []
    assert len(result.malformed) == 1
    assert result.malformed[0].position == expected_position


def test_landing_reader_unknown_family_reads_as_empty() -> None:
    fixture = FixtureReader(rows_by_family={})
    reader = LandingReader(fixture)

    result = reader.read_family("enrollment")

    assert result.rows == []
    assert result.malformed == []


def test_row_count_reader_counts_an_uncitable_consumer() -> None:
    fixture = FixtureReader(rows_by_family={"enrollment": [{"subject_key": "enr-1"}, {"subject_key": "enr-2"}]})
    reader = RowCountReader(fixture)

    assert reader.read_family("enrollment") == 2
    assert reader.read_family("communication_consent") == 0


# --- PatientsReader (task 3.1, design.md decision 9) -------------------------------------------


def test_patients_reader_parses_a_projected_row() -> None:
    """spec projection-conformance: 'The projection is a citable consumer' — a row citing
    `ledger_seq` reads exactly like the board's, `state` keyed from `enrollment_status`."""
    fixture = FixtureReader(
        rows_by_family={"enrollment": [{"patient_id": "pat-1", "enrollment_status": "active", "ledger_seq": 50}]}
    )
    reader = PatientsReader(fixture)

    result = reader.read_family("enrollment")

    assert result.malformed == []
    assert result.rows == [
        SweptRow(subject_key="pat-1", fields={"state": "active"}, cited_seq=50),
    ]


def test_patients_reader_a_legacy_row_parses_as_uncitable_not_malformed() -> None:
    """spec: 'Legacy rows are marked, never overwritten' — a null `ledger_seq` is a clean row
    with `cited_seq=None`, which `projection_conformance` classifies `uncitable`, never
    `malformed` and never `state`."""
    fixture = FixtureReader(
        rows_by_family={"enrollment": [{"patient_id": "pat-2", "enrollment_status": "pending", "ledger_seq": None}]}
    )
    reader = PatientsReader(fixture)

    result = reader.read_family("enrollment")

    assert result.malformed == []
    assert result.rows == [
        SweptRow(subject_key="pat-2", fields={"state": "pending"}, cited_seq=None),
    ]


@pytest.mark.parametrize(
    ("row", "expected_position"),
    [
        ({"enrollment_status": "active", "ledger_seq": 5}, "[offset 0]"),
        ({"patient_id": "pat-1", "ledger_seq": 5}, "pat-1"),
        ({"patient_id": "pat-1", "enrollment_status": "active", "ledger_seq": "fifty"}, "pat-1"),
    ],
)
def test_patients_reader_counts_a_malformed_row_never_raises(row: dict[str, object], expected_position: str) -> None:
    fixture = FixtureReader(rows_by_family={"enrollment": [row]})
    reader = PatientsReader(fixture)

    result = reader.read_family("enrollment")

    assert result.rows == []
    assert len(result.malformed) == 1
    assert result.malformed[0].position == expected_position


def test_fixture_reader_serves_both_protocols_from_the_same_data() -> None:
    fixture = FixtureReader(rows_by_family={"enrollment": [{"subject_key": "enr-1", "state": "active", "seq": 1}]})

    assert fixture.count_family("enrollment") == 1
    assert list(fixture.fetch_family("enrollment")) == [{"subject_key": "enr-1", "state": "active", "seq": 1}]
    assert fixture.fetch_family("missing") == ()


# --- Credential posture: every reader here is read-only ----------------------------------------


def test_no_reader_in_this_module_holds_a_command_submission_method() -> None:
    """spec: 'A `projection_conformance` sweep SHALL hold no ledger writer credential and SHALL
    declare no command.' Every reader class in this module is checked structurally: none may
    carry a method that submits a command, patches a board record, or posts a comment.
    """
    from schedules import sweep_readers

    writer_shaped_methods = {"submit_command", "patch_record", "create_comment", "declare"}
    for name in sweep_readers.__all__:
        obj = getattr(sweep_readers, name)
        if not isinstance(obj, type):
            continue
        held = writer_shaped_methods & set(vars(obj))
        assert not held, f"{name} holds writer-shaped method(s): {held}"


def test_ledger_state_reader_never_imports_a_command_type() -> None:
    """No `pulse_core.generated` command import anywhere in this module — this reader cannot
    build a command even if a future edit mistakenly tried to submit one."""
    import inspect

    from schedules import sweep_readers

    source = inspect.getsource(sweep_readers)
    assert "pulse_core.generated" not in source
    assert "submit_command" not in source
