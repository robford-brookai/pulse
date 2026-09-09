"""`schedules.receipt` — task 2.2's `Receipt` (design.md decision 7).

Builds a `FamilyConformance`/`DriftReceipt` directly (the same dataclasses
`test_projection_conformance.py` and `test_consent_sweep.py` already construct) rather than
re-running either sweep's own pipeline: this module's own job is the reshape into one receipt
line, not re-proving what task 2.1 or the consent sweep already prove about drift.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from schedules.consent_sweep import Correction, CorrectionDirection, DriftReceipt, ExportParseError, ExportRow
from schedules.projection_conformance import (
    Comparison,
    ConsumerConformance,
    FamilyConformance,
    UncitableConsumer,
)
from schedules.receipt import (
    SUBJECT_KEY_CAP,
    build_export_diff_receipt,
    build_projection_conformance_receipt,
    compute_streak,
    receipt_payload,
    rows_compared,
)

FLOOR = date(2026, 8, 26)


def _export_row(row_number: int, subject_key: str = "SUBJ-001", channel: str = "sms") -> ExportRow:
    return ExportRow(row_number=row_number, subject_key=subject_key, channel=channel, suppressed=True)


class TestProjectionConformanceReceiptClean:
    def test_a_clean_run_reports_zero_divergences_and_zero_uncitable(self) -> None:
        """Spec (reconciliation-sweeps): "A clean run leaves a countable receipt" — "one receipt
        line reports zero divergences and zero uncitable rows"."""
        conformance = FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=42,
            consumers=(
                ConsumerConformance(
                    consumer="twenty-board",
                    family="enrollment",
                    comparisons=(
                        Comparison(subject_key="enr-1", consumer="twenty-board", outcome="agreement"),
                        Comparison(subject_key="enr-2", consumer="twenty-board", outcome="agreement"),
                    ),
                ),
            ),
        )

        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        assert receipt.family == "enrollment"
        assert receipt.kind == "projection_conformance"
        assert receipt.floor == FLOOR
        assert receipt.snapshot_head == 42
        assert receipt.no_consumers is False
        assert len(receipt.consumers) == 1
        board = receipt.consumers[0]
        assert board.agreements == 2
        assert board.divergences == {}
        assert board.uncitable == 0
        assert board.in_flight == 0
        assert board.malformed == 0
        assert board.pre_floor == 0
        assert receipt.is_clean is True

    def test_payload_carries_the_pinned_tags(self) -> None:
        conformance = FamilyConformance(family="enrollment", floor=FLOOR, snapshot_head=1, consumers=())
        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        payload = receipt_payload(receipt)

        assert payload["tags"] == ["project:pulse", "service:schedules", "family:enrollment"]
        assert payload["date"] == "2026-09-08"
        assert payload["floor"] == "2026-08-26"
        assert payload["no_consumers"] is True


class TestProjectionConformanceReceiptDivergent:
    def test_a_divergence_is_named_by_subject_key_and_field(self) -> None:
        """Spec (projection-conformance): "Divergence names the subject, never the value"."""
        conformance = FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=10,
            consumers=(
                ConsumerConformance(
                    consumer="twenty-board",
                    family="enrollment",
                    comparisons=(
                        Comparison(subject_key="enr-1", consumer="twenty-board", outcome="agreement"),
                        Comparison(subject_key="enr-2", consumer="twenty-board", outcome="state", fields=("state",)),
                        Comparison(subject_key="enr-3", consumer="twenty-board", outcome="lag"),
                        Comparison(subject_key="enr-4", consumer="warehouse-landing", outcome="missing"),
                    ),
                ),
            ),
        )

        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        board = receipt.consumers[0]
        assert board.agreements == 1
        assert board.divergences == {"state": 1, "lag": 1, "missing": 1}
        assert board.subject_keys["state"].keys == ("enr-2",)
        assert board.subject_keys["state"].total == 1
        assert receipt.is_clean is False

        payload = receipt_payload(receipt)
        consumers = cast("list[dict[str, Any]]", payload["consumers"])
        assert consumers[0]["divergences"] == {"state": 1, "lag": 1, "missing": 1}
        # A divergence names the subject key, never the field's value — only the field name is
        # ever attached, and only inside projection_conformance.Comparison, never this receipt.
        assert "value" not in str(payload)

    def test_an_uncitable_consumer_reports_its_row_count_never_subject_keys(self) -> None:
        """Spec (projection-conformance): "The patients table is reported, not compared"."""
        conformance = FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=10,
            consumers=(
                ConsumerConformance(
                    consumer="graph-projection-patients",
                    family="enrollment",
                    uncitable_consumer=UncitableConsumer(
                        consumer="graph-projection-patients",
                        family="enrollment",
                        row_count=1500,
                        owning_change="m1-retire-patient-state",
                    ),
                ),
            ),
        )

        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        patients = receipt.consumers[0]
        assert patients.uncitable == 1500
        assert patients.subject_keys == {}
        assert patients.agreements == 0


class TestSubjectKeyCap:
    def test_more_than_the_cap_is_truncated_with_the_true_total_beside_it(self) -> None:
        comparisons = tuple(
            Comparison(subject_key=f"enr-{i}", consumer="warehouse-landing", outcome="missing")
            for i in range(SUBJECT_KEY_CAP + 50)
        )
        conformance = FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=1,
            consumers=(
                ConsumerConformance(consumer="warehouse-landing", family="enrollment", comparisons=comparisons),
            ),
        )

        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        tally = receipt.consumers[0].subject_keys["missing"]
        assert len(tally.keys) == SUBJECT_KEY_CAP
        assert tally.total == SUBJECT_KEY_CAP + 50
        assert receipt.consumers[0].divergences["missing"] == SUBJECT_KEY_CAP + 50


class TestComputeStreak:
    def _clean_receipt(self) -> FamilyConformance:
        return FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=1,
            consumers=(
                ConsumerConformance(
                    consumer="twenty-board",
                    family="enrollment",
                    comparisons=(Comparison(subject_key="enr-1", consumer="twenty-board", outcome="agreement"),),
                ),
            ),
        )

    def test_ten_consecutive_clean_days_yield_a_streak_of_ten(self) -> None:
        """Spec: "Ten clean receipts are readable as a streak" — computable from the receipt lines
        alone."""
        start = date(2026, 8, 1)
        receipts = [
            build_projection_conformance_receipt(self._clean_receipt(), run_date=start.replace(day=start.day + i))
            for i in range(10)
        ]

        assert compute_streak(receipts) == 10

    def test_a_divergent_day_breaks_the_streak_at_that_day(self) -> None:
        day1 = build_projection_conformance_receipt(self._clean_receipt(), run_date=date(2026, 8, 1))
        day2 = build_projection_conformance_receipt(self._clean_receipt(), run_date=date(2026, 8, 2))
        day4 = build_projection_conformance_receipt(self._clean_receipt(), run_date=date(2026, 8, 4))
        divergent_conformance = FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=1,
            consumers=(
                ConsumerConformance(
                    consumer="twenty-board",
                    family="enrollment",
                    comparisons=(
                        Comparison(subject_key="enr-9", consumer="twenty-board", outcome="state", fields=("state",)),
                    ),
                ),
            ),
        )
        day3_divergent = build_projection_conformance_receipt(divergent_conformance, run_date=date(2026, 8, 3))

        receipts = [day1, day2, day3_divergent, day4]

        assert compute_streak(receipts) == 1  # only 2026-08-04, the most recent, is clean

    def test_a_gap_in_the_calendar_breaks_the_streak(self) -> None:
        day1 = build_projection_conformance_receipt(self._clean_receipt(), run_date=date(2026, 8, 1))
        day3 = build_projection_conformance_receipt(self._clean_receipt(), run_date=date(2026, 8, 3))

        assert compute_streak([day1, day3]) == 1


class TestExportDiffReceipt:
    def test_a_correction_is_a_named_state_divergence(self) -> None:
        row = _export_row(1)
        correction = Correction(
            subject_key=row.subject_key, channel=row.channel, direction=CorrectionDirection.OPT_OUT, export_row=row
        )
        drift = DriftReceipt(agreements=2, opt_out_corrections=1, opt_in_corrections=0, unparseable=0, parse_errors=())

        receipt = build_export_diff_receipt(
            drift, family="communication_consent", run_date=date(2026, 9, 8), floor=FLOOR, corrections=(correction,)
        )

        assert receipt.kind == "export_diff"
        assert receipt.snapshot_head is None
        assert receipt.no_consumers is False
        consumer = receipt.consumers[0]
        assert consumer.agreements == 2
        assert consumer.divergences == {"state": 1}
        assert consumer.subject_keys["state"].keys == ("SUBJ-001:sms",)
        assert receipt.is_clean is False

    def test_a_fully_agreeing_export_is_clean(self) -> None:
        drift = DriftReceipt(agreements=3, opt_out_corrections=0, opt_in_corrections=0, unparseable=0, parse_errors=())

        receipt = build_export_diff_receipt(
            drift, family="communication_consent", run_date=date(2026, 9, 8), floor=FLOOR
        )

        assert receipt.is_clean is True
        assert receipt.consumers[0].divergences == {}

    def test_unparseable_rows_are_malformed_named_by_row_number(self) -> None:
        drift = DriftReceipt(
            agreements=0,
            opt_out_corrections=0,
            opt_in_corrections=0,
            unparseable=1,
            parse_errors=(ExportParseError(row_number=7, detail="missing 'suppressed'"),),
        )

        receipt = build_export_diff_receipt(
            drift, family="communication_consent", run_date=date(2026, 9, 8), floor=FLOOR
        )

        consumer = receipt.consumers[0]
        assert consumer.malformed == 1
        assert consumer.subject_keys["malformed"].keys == ("row:7",)
        # Never the row's other contents — only the position (spec: "Malformed rows are counted
        # and attached").
        assert "suppressed" not in str(receipt_payload(receipt))


class TestRowsCompared:
    def test_counts_every_classified_outcome_including_malformed(self) -> None:
        conformance = FamilyConformance(
            family="enrollment",
            floor=FLOOR,
            snapshot_head=1,
            consumers=(
                ConsumerConformance(
                    consumer="twenty-board",
                    family="enrollment",
                    comparisons=(
                        Comparison(subject_key="enr-1", consumer="twenty-board", outcome="agreement"),
                        Comparison(subject_key="enr-2", consumer="twenty-board", outcome="malformed"),
                    ),
                ),
            ),
        )
        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        assert rows_compared(receipt) == 2

    def test_no_consumers_at_all_counts_zero(self) -> None:
        conformance = FamilyConformance(family="coverage", floor=FLOOR, snapshot_head=None, consumers=())
        receipt = build_projection_conformance_receipt(conformance, run_date=date(2026, 9, 8))

        assert rows_compared(receipt) == 0
        assert receipt.no_consumers is True
