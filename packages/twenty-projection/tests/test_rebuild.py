"""The rebuild's whole claim: a projection repainted from the journal alone is the projection.

Pins the five `projection-rebuild` spec scenarios (pulse-demo-closeout task 2.3) against a
fixture Twenty REST surface and a fixture history source — no live network, no ledger database:

- "Destroy then rebuild is row-identical" — the projected columns are cleared and repainted, and
  the repainted row equals the one the *live* apply path produced, field for field. The captured
  rows in every test here are produced by `apply_event` itself rather than hand-written, because
  a hand-written expectation would only prove the rebuild agrees with the test author.
- "A rebuild over intact rows changes nothing" / "A rerun is a no-op" — zero PATCHes, and a
  receipt that says so, attributable to the operator who ran it.
- "A mixed history rebuilds to the live state" — forward, backdated, and reversal events fold to
  the same row incremental apply reached from the same events, in the same ledger sequence.
- "Scope is honored" — a row outside the named scope is never read into the fold and never
  written.

All data is synthetic: spine-shaped ids and program codes, never a name or a demographic.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pulse_core.client import HistoryRejectedError
from twenty_projection.apply import (
    V1_BOARD,
    AmbiguousSubjectError,
    ProjectionRestClient,
    SubjectLookupError,
    apply_event,
)
from twenty_projection.rebuild import (
    PROGRAM_COLUMN,
    HistoryScopeError,
    ScopeError,
    fold_history,
    main,
    parse_scope,
    rebuild,
)

PLURAL = "patientPrograms"
SUBJECT_TYPE = "enrollment"

#: Planted in an event payload so the PHI tripwire has something to look for: no receipt line and
#: no log line may ever carry a payload value.
PAYLOAD_SENTINEL = "synthetic-payload-value"


class FixtureTwenty:
    """An in-memory Twenty core REST surface: paged listing, filtered listing, PATCH by id.

    Mirrors the pinned conventions (`docs/contracts/consumes.md`): `filter=<field>[eq]:<value>`
    comma-joined AND, records under `data.<plural>`, `pageInfo.hasNextPage` / `endCursor` paging.
    Records every PATCH so a test can assert what was — and was not — written.
    """

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = {str(record["id"]): dict(record) for record in records}
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> ProjectionRestClient:
        token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
        return ProjectionRestClient("https://twenty.fixture", token=token, transport=self.transport())

    def row(self, record_id: str) -> dict[str, Any]:
        return dict(self.records[record_id])

    def clear_projection(self, record_id: str) -> None:
        """Destroy the projection for one row: the columns the projection owns, and only those.

        The projection never creates a board record — it resolves one through the denormalized
        key columns and repaints what it owns — so "the projection's rows are deleted" is this:
        status, its as-of, and the watermark gone, the subject's anchor row still there.
        """
        self.records[record_id].update({
            V1_BOARD.status_field: None,
            V1_BOARD.as_of_field: None,
            V1_BOARD.watermark_field: None,
        })

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if request.method == "GET" and path == f"/rest/{PLURAL}":
            return self._list(request)
        if request.method == "PATCH" and path.startswith(f"/rest/{PLURAL}/"):
            return self._patch(request, path.rsplit("/", 1)[1])
        return httpx.Response(404, json={})

    def _list(self, request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        predicates: dict[str, str] = {}
        raw_filter = params.get("filter", [""])[0]
        if raw_filter:
            for predicate in raw_filter.split(","):
                field, _, value = predicate.partition("[eq]:")
                predicates[field] = value
        matches = [
            record
            for record in self.records.values()
            if all(str(record.get(field)) == value for field, value in predicates.items())
        ]
        matches.sort(key=lambda record: str(record["id"]))
        after = params.get("starting_after", [None])[0]
        if after is not None:
            matches = [record for record in matches if str(record["id"]) > after]
        limit = int(params.get("limit", ["10"])[0])
        page, rest = matches[:limit], matches[limit:]
        page_info: dict[str, object] = {"hasNextPage": bool(rest)}
        if rest and page:
            page_info["endCursor"] = str(page[-1]["id"])
        return httpx.Response(200, json={"data": {PLURAL: page}, "pageInfo": page_info})

    def _patch(self, request: httpx.Request, record_id: str) -> httpx.Response:
        fields = json.loads(request.content)
        self.patches.append((record_id, fields))
        self.records[record_id].update(fields)
        return httpx.Response(200, json={"data": {"updatePatientProgram": self.row(record_id)}})


class FixtureHistory:
    """The ledger's replay surface as a fixture: one subject's committed events, in sequence.

    Stands in for `PulseCoreClient.subject_history` structurally — the same seam the rebuild
    takes in production, so no test here holds a ledger credential or a database handle.
    """

    def __init__(self, histories: Mapping[str, Sequence[Mapping[str, object]]]) -> None:
        self._histories = {key: list(events) for key, events in histories.items()}
        self.reads: list[tuple[str, str]] = []

    def subject_history(self, subject_type: str, subject_key: str) -> Sequence[Mapping[str, object]]:
        self.reads.append((subject_type, subject_key))
        return list(self._histories.get(subject_key, ()))


def board_record(
    record_id: str = "rec-1",
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    status: str | None = None,
    as_of: str | None = None,
    watermark: int | None = None,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "canonicalPatientId": subject,
        "programCode": program,
        V1_BOARD.status_field: status,
        V1_BOARD.as_of_field: as_of,
        V1_BOARD.watermark_field: watermark,
    }


def enrollment_event(
    *,
    subject: str = "pt-0001",
    program: str = "CCM",
    to_state: str = "active",
    seq: int = 1,
    event_id: str | None = None,
    effective_at: str = "2026-08-18T12:00:00+00:00",
) -> dict[str, Any]:
    """A committed enrollment envelope as the relay publishes it, plus a payload tripwire value."""
    return {
        "event_id": event_id or f"evt-{seq}",
        "event_type": "enrollment.declared",
        "subject_type": SUBJECT_TYPE,
        "subject_key": subject,
        "seq": seq,
        "effective_at": effective_at,
        "payload": {"to_state": to_state, "program": program, "note": PAYLOAD_SENTINEL},
    }


#: One subject's mixed history: two forward declarations, a *backdated* correction (a later ledger
#: sequence carrying an earlier effective time), and a reversal back off it.
#:
#: The effective times are deliberately not sorted with the sequences, and the last event in ledger
#: sequence is not the one with the latest effective time. That is the whole discriminating power of
#: these fixtures: a fold that ordered by effective time would land on seq 2 and produce a row the
#: live consumer never had — a row that looks defensible, passes a demo, and lies.
MIXED_HISTORY: tuple[dict[str, Any], ...] = (
    enrollment_event(seq=1, to_state="pending_start", effective_at="2026-08-01T00:00:00+00:00"),
    enrollment_event(seq=2, to_state="active", effective_at="2026-08-18T12:00:00+00:00"),
    enrollment_event(seq=3, to_state="on_hold", effective_at="2026-08-10T09:00:00+00:00"),
    enrollment_event(seq=4, to_state="active", effective_at="2026-08-11T07:15:00+00:00"),
)


def live_applied_row(events: Sequence[Mapping[str, Any]], record: dict[str, Any]) -> dict[str, Any]:
    """The row incremental apply reaches from `events` — the projection's own write path, run."""
    fixture = FixtureTwenty([record])
    with fixture.client() as client:
        for event in events:
            apply_event(event, client=client)
    return fixture.row(str(record["id"]))


# --- Scope parsing ------------------------------------------------------------------------------


def test_scope_parses_a_subject_type_and_an_optional_key() -> None:
    whole = parse_scope("enrollment")
    assert (whole.subject_type, whole.subject_key, whole.label) == (SUBJECT_TYPE, None, "enrollment")
    one = parse_scope("enrollment:pt-0001")
    assert (one.subject_type, one.subject_key, one.label) == (SUBJECT_TYPE, "pt-0001", "enrollment:pt-0001")


@pytest.mark.parametrize("raw", ["", ":", "enrollment:", ":pt-0001", "enrollment:pt:0001", "  "])
def test_a_malformed_scope_is_refused(raw: str) -> None:
    with pytest.raises(ScopeError):
        parse_scope(raw)


def test_a_scope_naming_another_subject_type_than_the_board_is_refused() -> None:
    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client, pytest.raises(ScopeError):
        rebuild(parse_scope("billing_episode"), history=FixtureHistory({}), client=client, operator="op-1")


# --- The fold: same ordering rules as live apply ------------------------------------------------


def test_the_fold_takes_the_last_event_per_program_in_ledger_sequence() -> None:
    folded = fold_history(MIXED_HISTORY, board=V1_BOARD)
    assert set(folded) == {"CCM"}
    fields = folded["CCM"].fields
    assert fields[V1_BOARD.watermark_field] == 4
    # The last event in *ledger sequence*, not the latest effective time (seq 2's 08-18).
    assert fields[V1_BOARD.as_of_field] == "2026-08-11T07:15:00+00:00"


def test_the_fold_applies_the_watermark_guard_live_apply_applies() -> None:
    """A lower sequence arriving after a higher one is skipped, exactly as `apply_event` skips it.

    The history route returns ledger sequence, so this ordering should not occur; the guard is
    shared with live apply so that if it ever does, the fold and the queue agree about it.
    """
    out_of_order = (MIXED_HISTORY[0], MIXED_HISTORY[3], MIXED_HISTORY[2], MIXED_HISTORY[1])
    assert (
        fold_history(out_of_order, board=V1_BOARD)["CCM"].fields
        == fold_history(MIXED_HISTORY, board=V1_BOARD)["CCM"].fields
    )


def test_the_fold_keeps_one_state_per_program() -> None:
    """A subject's `subject_key` is the canonical patient id; the program is in the payload, and
    each program is a separate board row — so the fold is per program, as live apply's per-record
    watermark is."""
    history = (
        enrollment_event(seq=1, program="CCM", to_state="active"),
        enrollment_event(seq=2, program="RPM", to_state="pending_start"),
        enrollment_event(seq=3, program="CCM", to_state="on_hold"),
    )
    folded = fold_history(history, board=V1_BOARD)
    assert set(folded) == {"CCM", "RPM"}
    assert folded["CCM"].fields[V1_BOARD.watermark_field] == 3
    assert folded["RPM"].fields[V1_BOARD.watermark_field] == 2


# --- Scenario: destroy then rebuild is row-identical --------------------------------------------


def test_destroy_then_rebuild_is_row_identical() -> None:
    captured = live_applied_row(MIXED_HISTORY, board_record())

    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client:
        for event in MIXED_HISTORY:
            apply_event(event, client=client)
        assert fixture.row("rec-1") == captured
        fixture.clear_projection("rec-1")
        fixture.patches.clear()

        receipt = rebuild(
            parse_scope("enrollment:pt-0001"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )
        verify = rebuild(
            parse_scope("enrollment:pt-0001"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )

    assert fixture.row("rec-1") == captured
    assert receipt.rows_written == 1
    assert receipt.events_read == len(MIXED_HISTORY)
    assert receipt.rows_read == 1
    assert verify.rows_written == 0
    assert verify.differences == 0


# --- Scenario: a rebuild over intact rows changes nothing ---------------------------------------


def test_rebuild_over_intact_rows_writes_nothing() -> None:
    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client:
        for event in MIXED_HISTORY:
            apply_event(event, client=client)
        fixture.patches.clear()
        receipt = rebuild(
            parse_scope("enrollment:pt-0001"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )
    assert fixture.patches == []
    assert (receipt.rows_written, receipt.differences) == (0, 0)


def test_an_as_of_in_another_iso_rendering_is_not_a_difference() -> None:
    """Twenty answers a DATE_TIME as UTC with a `Z` and milliseconds. The same instant in another
    rendering is not a difference — a rebuild that PATCHed over it would write on every run."""
    fixture = FixtureTwenty([
        board_record(
            status="ACTIVE",
            as_of="2026-08-11T07:15:00.000Z",
            watermark=4,
        )
    ])
    with fixture.client() as client:
        receipt = rebuild(
            parse_scope("enrollment:pt-0001"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )
    assert fixture.patches == []
    assert (receipt.rows_written, receipt.differences) == (0, 0)


# --- Scenario: a mixed history rebuilds to the live state ---------------------------------------


def test_mixed_history_rebuilds_to_the_live_apply_state() -> None:
    captured = live_applied_row(MIXED_HISTORY, board_record())

    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client:
        receipt = rebuild(
            parse_scope("enrollment:pt-0001"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )

    assert fixture.row("rec-1") == captured
    assert receipt.rows_written == 1
    assert sorted(receipt.outcomes[0].differing_fields) == sorted((
        V1_BOARD.status_field,
        V1_BOARD.as_of_field,
        V1_BOARD.watermark_field,
    ))


# --- Scenario: a rerun is a no-op, and both receipts name their operator ------------------------


def test_a_rerun_is_a_noop_and_both_receipts_name_their_operator() -> None:
    fixture = FixtureTwenty([board_record()])
    history = FixtureHistory({"pt-0001": MIXED_HISTORY})
    with fixture.client() as client:
        first = rebuild(parse_scope("enrollment:pt-0001"), history=history, client=client, operator="op-1")
        fixture.patches.clear()
        second = rebuild(parse_scope("enrollment:pt-0001"), history=history, client=client, operator="op-2")
    assert first.rows_written == 1
    assert (second.rows_written, second.differences, fixture.patches) == (0, 0, [])
    assert (first.operator, second.operator) == ("op-1", "op-2")
    assert "op-2" in second.render()


# --- Scenario: scope is honored -----------------------------------------------------------------


def test_rows_outside_the_named_scope_are_untouched() -> None:
    other = board_record("rec-2", subject="pt-0002")
    fixture = FixtureTwenty([board_record(), other])
    history = FixtureHistory({"pt-0001": MIXED_HISTORY, "pt-0002": (enrollment_event(subject="pt-0002", seq=7),)})
    with fixture.client() as client:
        receipt = rebuild(parse_scope("enrollment:pt-0001"), history=history, client=client, operator="op-1")

    assert [record_id for record_id, _ in fixture.patches] == ["rec-1"]
    assert fixture.row("rec-2") == other
    assert history.reads == [(SUBJECT_TYPE, "pt-0001")]
    assert (receipt.rows_read, receipt.subjects) == (1, 1)


def test_a_keyless_scope_rebuilds_every_subject_the_board_holds() -> None:
    fixture = FixtureTwenty([board_record(), board_record("rec-2", subject="pt-0002")])
    history = FixtureHistory({
        "pt-0001": MIXED_HISTORY,
        "pt-0002": (enrollment_event(subject="pt-0002", seq=7, to_state="ended"),),
    })
    with fixture.client() as client:
        receipt = rebuild(parse_scope("enrollment"), history=history, client=client, operator="op-1")

    assert sorted(record_id for record_id, _ in fixture.patches) == ["rec-1", "rec-2"]
    assert (receipt.subjects, receipt.rows_read, receipt.rows_written) == (2, 2, 2)
    assert history.reads == [(SUBJECT_TYPE, "pt-0001"), (SUBJECT_TYPE, "pt-0002")]


def test_a_scope_paged_by_the_board_listing_still_sees_every_row() -> None:
    """The board is listed with paging, so a scope wider than one page is not silently truncated."""
    records = [board_record(f"rec-{index}", subject=f"pt-{index:04d}") for index in range(1, 6)]
    history = FixtureHistory({
        f"pt-{index:04d}": (enrollment_event(subject=f"pt-{index:04d}", seq=index),) for index in range(1, 6)
    })
    fixture = FixtureTwenty(records)
    with fixture.client() as client:
        receipt = rebuild(parse_scope("enrollment"), history=history, client=client, operator="op-1", page_size=2)
    assert receipt.subjects == 5
    assert receipt.rows_written == 5


# --- Dispositions the drill must survive --------------------------------------------------------


def test_a_subject_with_no_committed_events_is_left_alone() -> None:
    fixture = FixtureTwenty([board_record(status="ACTIVE", as_of="2026-08-18T12:00:00+00:00", watermark=1)])
    with fixture.client() as client:
        receipt = rebuild(parse_scope("enrollment"), history=FixtureHistory({}), client=client, operator="op-1")
    assert fixture.patches == []
    assert (receipt.rows_written, receipt.subjects) == (0, 1)
    assert receipt.outcomes[0].disposition == "no_events"


def test_a_subject_with_no_board_row_is_a_counted_orphan_not_a_crash() -> None:
    fixture = FixtureTwenty([board_record("rec-2", subject="pt-0002")])
    history = FixtureHistory({"pt-0001": MIXED_HISTORY})
    with fixture.client() as client:
        receipt = rebuild(parse_scope("enrollment:pt-0001"), history=history, client=client, operator="op-1")
    assert fixture.patches == []
    assert receipt.orphans == 1
    assert receipt.outcomes[0].disposition == "orphan"


def test_a_scope_key_carrying_a_filter_reserved_character_is_refused() -> None:
    """Twenty's filter grammar has no quoting, so such a key has no expressible predicate."""
    with pytest.raises(ScopeError):
        parse_scope("enrollment:pt,0001")


# --- Payload posture ----------------------------------------------------------------------------


def test_no_payload_value_reaches_the_receipt_or_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client:
        receipt = rebuild(
            parse_scope("enrollment:pt-0001"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )
    rendered = receipt.render()
    assert PAYLOAD_SENTINEL not in rendered
    assert PAYLOAD_SENTINEL not in caplog.text
    # Field *names* are the receipt's vocabulary for a difference, never field values.
    assert V1_BOARD.status_field in rendered


# --- The CLI entry ------------------------------------------------------------------------------


def _cli_env() -> dict[str, str]:
    return {
        "PULSE_TWENTY_DEV_URL": "https://twenty.fixture",
        "PULSE_TWENTY_DEV_TOKEN": "fixture-token",
        "PULSE_CORE_BASE_URL": "https://ledger.fixture",
        "PULSE_CORE_REPLAY_TOKEN": "fixture-replay-token",
    }


def test_cli_rebuilds_the_named_scope_and_prints_the_receipt(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client:
        code = main(
            ["--scope", "enrollment:pt-0001", "--target", "dev", "--operator", "op-1"],
            env=_cli_env(),
            client=client,
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
        )
    printed = capsys.readouterr().out
    assert code == 0
    assert "enrollment:pt-0001" in printed
    assert "op-1" in printed
    assert fixture.patches != []


@pytest.mark.parametrize(
    ("dropped", "named"),
    [
        ("PULSE_TWENTY_DEV_TOKEN", "PULSE_TWENTY_DEV_TOKEN"),
        ("PULSE_CORE_BASE_URL", "PULSE_CORE_BASE_URL"),
        ("PULSE_CORE_REPLAY_TOKEN", "PULSE_CORE_REPLAY_TOKEN"),
    ],
)
def test_cli_fails_by_name_on_a_missing_variable(dropped: str, named: str, capsys: pytest.CaptureFixture[str]) -> None:
    env = _cli_env()
    del env[dropped]
    code = main(["--scope", "enrollment:pt-0001", "--target", "dev", "--operator", "op-1"], env=env)
    assert code == 2
    assert named in capsys.readouterr().err


def test_cli_refuses_a_malformed_scope(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--scope", "enrollment:", "--target", "dev", "--operator", "op-1"], env=_cli_env())
    assert code == 2
    assert "scope" in capsys.readouterr().err


# --- Faults the rebuild must surface rather than paper over ------------------------------------


def test_a_history_carrying_another_subjects_event_is_refused() -> None:
    """A replay source that mixed subjects would repaint one subject's row from another's events."""
    fixture = FixtureTwenty([board_record()])
    history = FixtureHistory({"pt-0001": (enrollment_event(subject="pt-0002", seq=1),)})
    with fixture.client() as client, pytest.raises(HistoryScopeError):
        rebuild(parse_scope("enrollment:pt-0001"), history=history, client=client, operator="op-1")
    assert fixture.patches == []


def test_duplicate_identity_columns_are_a_data_fault_not_a_picked_winner() -> None:
    fixture = FixtureTwenty([board_record(), board_record("rec-2")])
    history = FixtureHistory({"pt-0001": MIXED_HISTORY})
    with fixture.client() as client, pytest.raises(AmbiguousSubjectError):
        rebuild(parse_scope("enrollment:pt-0001"), history=history, client=client, operator="op-1")
    assert fixture.patches == []


def test_a_row_with_no_identity_columns_is_never_painted() -> None:
    """The projection resolves through the identity columns; a row without them addresses no
    subject, so no event can reach it and a keyless rebuild must leave it exactly where it is."""
    anonymous = board_record("rec-9", status="ACTIVE")
    del anonymous[PROGRAM_COLUMN]
    fixture = FixtureTwenty([board_record(), anonymous])
    with fixture.client() as client:
        receipt = rebuild(
            parse_scope("enrollment"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )
    assert [record_id for record_id, _ in fixture.patches] == ["rec-1"]
    assert fixture.row("rec-9") == anonymous
    assert receipt.rows_read == 1


def test_a_listing_claiming_a_next_page_with_no_cursor_raises_rather_than_loops() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {PLURAL: [board_record()]}, "pageInfo": {"hasNextPage": True}})

    token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
    with (
        ProjectionRestClient("https://twenty.fixture", token=token, transport=httpx.MockTransport(handle)) as client,
        pytest.raises(SubjectLookupError),
    ):
        rebuild(parse_scope("enrollment"), history=FixtureHistory({}), client=client, operator="op-1")


def test_a_listed_row_with_no_id_cannot_be_written() -> None:
    record = board_record()
    del record["id"]

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {PLURAL: [record]}, "pageInfo": {"hasNextPage": False}})

    token = "fixture-token"  # noqa: S105 — a fixture placeholder, not a credential
    with (
        ProjectionRestClient("https://twenty.fixture", token=token, transport=httpx.MockTransport(handle)) as client,
        pytest.raises(SubjectLookupError),
    ):
        rebuild(
            parse_scope("enrollment"),
            history=FixtureHistory({"pt-0001": MIXED_HISTORY}),
            client=client,
            operator="op-1",
        )


def test_a_refused_history_read_exits_nonzero_without_writing(capsys: pytest.CaptureFixture[str]) -> None:
    """ "I could not read the events" is not "this subject has none" — the run fails, loudly."""

    class RefusingHistory:
        def subject_history(self, subject_type: str, subject_key: str) -> Sequence[Mapping[str, object]]:
            raise HistoryRejectedError(403)

    fixture = FixtureTwenty([board_record()])
    with fixture.client() as client:
        code = main(
            ["--scope", "enrollment:pt-0001", "--target", "dev", "--operator", "op-1"],
            env=_cli_env(),
            client=client,
            history=RefusingHistory(),
        )
    assert code == 1
    assert fixture.patches == []
    assert "enrollment:pt-0001" in capsys.readouterr().err
