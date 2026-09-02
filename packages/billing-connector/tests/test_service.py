"""`billing_connector.service` — task 1.3 scaffold stub.

Behavior fills in across wave 1; this module only pins `main`'s and `run_batch`'s signatures and
that their bodies are not yet implemented.
"""

from __future__ import annotations

import inspect

import pytest
from billing_connector.service import main, run_batch


class TestRunBatchSignature:
    def test_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(run_batch).parameters) == ["store", "config", "client", "envelope"]

    def test_return_annotation_is_receipt(self) -> None:
        assert inspect.signature(run_batch).return_annotation == "Receipt"

    def test_body_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            run_batch(store=object(), config=object(), client=object(), envelope={})  # type: ignore[arg-type]


class TestMainSignature:
    def test_signature_matches_the_work_order(self) -> None:
        assert list(inspect.signature(main).parameters) == ["argv"]

    def test_return_annotation_is_int(self) -> None:
        assert inspect.signature(main).return_annotation == "int"

    def test_body_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            main([])
