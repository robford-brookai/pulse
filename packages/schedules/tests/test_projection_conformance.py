"""`schedules.projection_conformance` — task 2.1's classifier.

One golden fixture per outcome kind lives in `tests/fixtures/projection_conformance/`, each
naming the spec scenario it pins, so the classification table is data a reviewer can read rather
than assertions spread across the suite. The remaining tests cover what a fixture cannot state:
that the pinned floor still equals the date in `docs/contracts/publishes.md`, that an uncitable
consumer is never compared row by row, and that no field value from either side reaches a result
(the PHI tripwire).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from schedules.projection_conformance import (
    MIN_COMPLETE_FROM,
    Comparison,
    ConsumerConformance,
    FamilyConformance,
    SubjectSnapshot,
    UncitableConsumer,
    compare_family,
    conform_family,
    report_uncitable_consumer,
    snapshot_from_read,
)
from schedules.sweep_readers import FamilyRead, MalformedRow, SubjectRead, SweptRow
from schedules.sweep_registry import Consumer

FIXTURES = Path(__file__).parent / "fixtures" / "projection_conformance"
REPO_ROOT = Path(__file__).resolve().parents[3]

OUTCOME_KINDS = (
    "agreement",
    "state",
    "lag",
    "missing",
    "orphan",
    "uncitable_row",
    "uncitable_consumer",
    "in_flight",
    "pre_floor",
    "malformed",
)


# --- fixture loading ------------------------------------------------------------------------


def _load(name: str) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", json.loads((FIXTURES / f"{name}.json").read_text()))


def _consumer(spec: Mapping[str, Any]) -> Consumer:
    return Consumer(
        name=cast("str", spec["name"]),
        families=("enrollment",),
        reader=None,
        cite_field=cast("str | None", spec["cite_field"]),
        freshness_budget_s=cast("int", spec["freshness_budget_s"]),
        owning_change=cast("str | None", spec.get("owning_change")),
    )


def _snapshot(entries: Sequence[Mapping[str, Any]]) -> dict[str, SubjectSnapshot]:
    return {
        cast("str", entry["subject_key"]): SubjectSnapshot(
            subject_key=cast("str", entry["subject_key"]),
            head_seq=cast("int | None", entry["head_seq"]),
            fields=cast("Mapping[str, str]", entry["fields"]),
            head_recorded_at=datetime.fromisoformat(cast("str", entry["head_recorded_at"])),
        )
        for entry in entries
    }


def _read(fixture: Mapping[str, Any]) -> FamilyRead:
    rows = [
        SweptRow(
            subject_key=cast("str", raw["subject_key"]),
            fields=cast("Mapping[str, str]", raw["fields"]),
            cited_seq=cast("int | None", raw["cited_seq"]),
        )
        for raw in cast("Sequence[Mapping[str, Any]]", fixture["rows"])
    ]
    malformed = [
        MalformedRow(position=cast("str", raw["position"]), detail=cast("str", raw["detail"]))
        for raw in cast("Sequence[Mapping[str, Any]]", fixture["malformed"])
    ]
    return FamilyRead(rows=rows, malformed=malformed)


def _expected(fixture: Mapping[str, Any]) -> list[Comparison]:
    return [
        Comparison(
            subject_key=cast("str", raw["subject_key"]),
            consumer=cast("str", cast("Mapping[str, Any]", fixture["consumer"])["name"]),
            outcome=raw["outcome"],
            fields=tuple(cast("Sequence[str]", raw["fields"])),
        )
        for raw in cast("Sequence[Mapping[str, Any]]", fixture["expected"])
    ]


def _run(fixture: Mapping[str, Any]) -> ConsumerConformance:
    consumer = _consumer(cast("Mapping[str, Any]", fixture["consumer"]))
    family = cast("str", fixture["family"])
    if consumer.uncitable:
        return report_uncitable_consumer(family=family, consumer=consumer, row_count=cast("int", fixture["row_count"]))
    return compare_family(
        family=family,
        consumer=consumer,
        snapshot=_snapshot(cast("Sequence[Mapping[str, Any]]", fixture["snapshot"])),
        read=_read(fixture),
        as_of=datetime.fromisoformat(cast("str", fixture["as_of"])),
    )


# --- one golden fixture per outcome kind ----------------------------------------------------


@pytest.mark.parametrize("kind", OUTCOME_KINDS)
def test_golden_outcome(kind: str) -> None:
    fixture = _load(kind)
    result = _run(fixture)
    assert sorted(result.comparisons, key=lambda c: c.subject_key) == sorted(
        _expected(fixture), key=lambda c: c.subject_key
    )
    expected_class = fixture.get("expected_uncitable_consumer")
    if expected_class is None:
        assert result.uncitable_consumer is None
    else:
        assert result.uncitable_consumer == UncitableConsumer(**cast("Mapping[str, Any]", expected_class))


def test_every_outcome_kind_has_a_fixture() -> None:
    assert {path.stem for path in FIXTURES.glob("*.json")} == set(OUTCOME_KINDS)


# --- the floor ------------------------------------------------------------------------------


def test_floor_equals_the_published_contract_date() -> None:
    """The pinned floor cannot drift from `publishes.md` silently (design decision 5)."""
    published = (REPO_ROOT / "docs" / "contracts" / "publishes.md").read_text()
    marker = "`min_complete_from`: `"
    start = published.index(marker) + len(marker)
    assert date.fromisoformat(published[start : start + len("2026-08-26")]) == MIN_COMPLETE_FROM


def test_a_subject_whose_history_predates_the_floor_is_never_a_divergence() -> None:
    consumer = _consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"]))
    snapshot = {
        "enr-old": SubjectSnapshot(
            subject_key="enr-old",
            head_seq=2,
            fields={"state": "active"},
            head_recorded_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
    }
    result = compare_family(
        family="enrollment",
        consumer=consumer,
        snapshot=snapshot,
        # A row that disagrees on state *and* cites nothing — below the floor, still `pre_floor`.
        read=FamilyRead(rows=[SweptRow("enr-old", {"state": "withdrawn"}, None)], malformed=[]),
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
    )
    assert result.counts() == {"pre_floor": 1}


# --- freshness budgets ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("age_s", "outcome"),
    [(30, "in_flight"), (90, "lag")],
)
def test_a_behind_citation_inside_the_budget_is_in_flight_not_lag(age_s: int, outcome: str) -> None:
    """The board's 60 s budget (design decision 4): a head this recent is not yet due."""
    as_of = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    consumer = _consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"]))
    result = compare_family(
        family="enrollment",
        consumer=consumer,
        snapshot={
            "enr-1": SubjectSnapshot(
                subject_key="enr-1",
                head_seq=7,
                fields={"state": "on_hold"},
                head_recorded_at=as_of - timedelta(seconds=age_s),
            )
        },
        read=FamilyRead(rows=[SweptRow("enr-1", {"state": "active"}, 6)], malformed=[]),
        as_of=as_of,
    )
    assert result.counts() == {outcome: 1}


def test_a_subject_missing_from_a_consumer_inside_the_budget_is_in_flight() -> None:
    as_of = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    consumer = _consumer(cast("Mapping[str, Any]", _load("missing")["consumer"]))
    result = compare_family(
        family="enrollment",
        consumer=consumer,
        snapshot={
            "enr-1": SubjectSnapshot(
                subject_key="enr-1",
                head_seq=7,
                fields={"state": "active"},
                head_recorded_at=as_of - timedelta(minutes=5),
            )
        },
        read=FamilyRead(rows=[], malformed=[]),
        as_of=as_of,
    )
    assert result.counts() == {"in_flight": 1}


def test_an_unknown_head_time_gets_no_grace() -> None:
    """No head time means no evidence the head is recent; a behind citation is `lag`."""
    result = compare_family(
        family="enrollment",
        consumer=_consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"])),
        snapshot={"enr-1": SubjectSnapshot("enr-1", 7, {"state": "active"}, None)},
        read=FamilyRead(rows=[SweptRow("enr-1", {"state": "active"}, 6)], malformed=[]),
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
    )
    assert result.counts() == {"lag": 1}


# --- the uncitable consumer -----------------------------------------------------------------


def test_an_uncitable_consumer_is_never_compared_row_by_row() -> None:
    consumer = _consumer(cast("Mapping[str, Any]", _load("uncitable_consumer")["consumer"]))
    with pytest.raises(ValueError, match="graph-projection-patients"):
        compare_family(
            family="enrollment",
            consumer=consumer,
            snapshot={},
            read=FamilyRead(rows=[], malformed=[]),
            as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        )


def test_a_citable_consumer_is_not_reported_as_a_class() -> None:
    consumer = _consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"]))
    with pytest.raises(ValueError, match="twenty-board"):
        report_uncitable_consumer(family="enrollment", consumer=consumer, row_count=3)


# --- family aggregation ---------------------------------------------------------------------


def test_one_divergence_is_one_named_line() -> None:
    fixture = _load("state")
    result = _run(fixture)
    family = conform_family(
        family="enrollment",
        snapshot=_snapshot(cast("Sequence[Mapping[str, Any]]", fixture["snapshot"])),
        consumers=[result],
    )
    assert family.counts() == {"state": 1, "agreement": 1}
    assert family.subject_keys()["state"] == ("enr-1",)
    assert family.snapshot_head == 7
    assert family.floor == MIN_COMPLETE_FROM
    assert not family.no_consumers


def test_a_family_with_no_consumers_passes() -> None:
    family = conform_family(family="enrollment", snapshot={}, consumers=[])
    assert family.no_consumers
    assert family.counts() == {}
    assert family.snapshot_head is None


def test_snapshot_from_read_carries_the_head_and_its_time() -> None:
    read = SubjectRead(row=SweptRow("enr-1", {"state": "active"}, 7), malformed=[])
    recorded_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert snapshot_from_read("enr-1", read, head_recorded_at=recorded_at) == SubjectSnapshot(
        subject_key="enr-1", head_seq=7, fields={"state": "active"}, head_recorded_at=recorded_at
    )


def test_snapshot_from_read_of_an_unknown_subject_has_no_state() -> None:
    snapshot = snapshot_from_read("enr-1", SubjectRead(row=None, malformed=[]))
    assert snapshot.fields is None
    assert snapshot.head_seq is None


def test_a_snapshot_subject_the_ledger_has_no_state_for_is_an_orphan_when_a_row_exists() -> None:
    result = compare_family(
        family="enrollment",
        consumer=_consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"])),
        snapshot={"enr-1": SubjectSnapshot("enr-1", None, None, None)},
        read=FamilyRead(rows=[SweptRow("enr-1", {"state": "active"}, 3)], malformed=[]),
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
    )
    assert result.counts() == {"orphan": 1}


def test_a_ledger_state_with_no_readable_head_is_malformed_not_agreement() -> None:
    result = compare_family(
        family="enrollment",
        consumer=_consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"])),
        snapshot={"enr-1": SubjectSnapshot("enr-1", None, {"state": "active"}, None)},
        read=FamilyRead(rows=[SweptRow("enr-1", {"state": "active"}, 3)], malformed=[]),
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
    )
    assert result.counts() == {"malformed": 1}


# --- PHI tripwire ---------------------------------------------------------------------------


def test_no_field_value_from_either_side_reaches_any_result() -> None:
    """Field *names* are reported, values never are (spec: "naming the differing field, and
    carries neither value"). Distinctive value tokens on both sides must appear nowhere in the
    results, at any depth."""
    ledger_value = "LEDGER_VALUE_TRIPWIRE"
    consumer_value = "CONSUMER_VALUE_TRIPWIRE"
    as_of = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    consumer = _consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"]))
    snapshot = {
        "enr-1": SubjectSnapshot(
            subject_key="enr-1",
            head_seq=7,
            fields={"state": ledger_value},
            head_recorded_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    }
    result = compare_family(
        family="enrollment",
        consumer=consumer,
        snapshot=snapshot,
        read=FamilyRead(
            rows=[SweptRow("enr-1", {"state": consumer_value}, 7)],
            malformed=[MalformedRow(position="[offset 4]", detail="'ledger_seq' is not an int")],
        ),
        as_of=as_of,
    )
    family = conform_family(family="enrollment", snapshot=snapshot, consumers=[result])
    serialized = json.dumps(asdict(family), default=str)
    assert ledger_value not in serialized
    assert consumer_value not in serialized
    assert "state" in serialized  # the field name itself is reported


def test_nothing_is_corrected() -> None:
    """The classifier is pure functions over reader outputs: it holds no writer at all."""
    import schedules.projection_conformance as module

    forbidden = ("client", "declare", "submit", "write", "patch", "rebuild")
    assert not [name for name in dir(module) if any(word in name.lower() for word in forbidden)]


def test_inputs_are_not_mutated() -> None:
    snapshot = {"enr-1": SubjectSnapshot("enr-1", 7, {"state": "active"}, None)}
    read = FamilyRead(rows=[SweptRow("enr-1", {"state": "active"}, 7)], malformed=[])
    compare_family(
        family="enrollment",
        consumer=_consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"])),
        snapshot=snapshot,
        read=read,
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
    )
    assert list(snapshot) == ["enr-1"]
    assert read.rows == [SweptRow("enr-1", {"state": "active"}, 7)]
    assert read.malformed == []


def test_family_conformance_is_frozen() -> None:
    family = conform_family(family="enrollment", snapshot={}, consumers=[])
    assert isinstance(family, FamilyConformance)
    with pytest.raises(Exception, match="cannot assign"):
        family.family = "other"  # type: ignore[misc]


def test_a_subject_the_ledger_holds_no_state_for_and_no_row_exists_for_is_not_counted() -> None:
    """Nothing on either side: counting it would inflate whichever kind it landed in."""
    result = compare_family(
        family="enrollment",
        consumer=_consumer(cast("Mapping[str, Any]", _load("agreement")["consumer"])),
        snapshot={"enr-1": SubjectSnapshot("enr-1", None, None, None)},
        read=FamilyRead(rows=[], malformed=[]),
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
    )
    assert result.comparisons == ()
    assert result.counts() == {}


def test_a_consumer_result_names_its_own_divergent_subjects() -> None:
    result = _run(_load("state"))
    assert result.subject_keys() == {"state": ("enr-1",), "agreement": ("enr-2",)}
