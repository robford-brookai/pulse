"""`billing_connector.receipts` — task 1.3.

`Receipt` and `format_line` are this scaffold task's one piece of real behavior (every other stub
raises `NotImplementedError`): the golden below is the shape every later change's receipt output
is pinned against (spec: "The receipt shape is stable").
"""

from __future__ import annotations

from billing_connector.receipts import Receipt
from pulse_core.connector.declare import DeclareCounts

#: The golden line for an all-zero receipt — the shape every run's line matches byte for byte
#: apart from the counts (spec scenario: "The receipt shape is stable").
_GOLDEN_ZERO_LINE = "service=billing-connector committed=0 replayed=0 rejected=0 evaluated=0 deferred=0"


class TestReceiptExtendsTheKitsCountedReceipt:
    def test_receipt_is_a_declare_counts(self) -> None:
        assert issubclass(Receipt, DeclareCounts)

    def test_receipt_defaults_to_an_all_zero_count(self) -> None:
        receipt = Receipt()

        assert (receipt.committed, receipt.replayed, receipt.rejected) == (0, 0, 0)
        assert (receipt.evaluated, receipt.deferred) == (0, 0)

    def test_receipt_carries_the_kits_three_counts_plus_its_own_two(self) -> None:
        receipt = Receipt(committed=1, replayed=2, rejected=3, evaluated=4, deferred=5)

        assert receipt.committed == 1
        assert receipt.replayed == 2
        assert receipt.rejected == 3
        assert receipt.evaluated == 4
        assert receipt.deferred == 5


class TestFormatLineGolden:
    def test_an_all_zero_receipt_matches_the_golden_line(self) -> None:
        assert Receipt().format_line() == _GOLDEN_ZERO_LINE

    def test_only_the_counts_vary_from_the_golden_shape(self) -> None:
        receipt = Receipt(committed=3, replayed=1, rejected=0, evaluated=4, deferred=2)

        line = receipt.format_line()

        assert line == "service=billing-connector committed=3 replayed=1 rejected=0 evaluated=4 deferred=2"
        # Same key order, same key set, as the golden — only the values differ.
        golden_keys = [pair.split("=", 1)[0] for pair in _GOLDEN_ZERO_LINE.split(" ")]
        line_keys = [pair.split("=", 1)[0] for pair in line.split(" ")]
        assert line_keys == golden_keys
