"""pulse_ledger is importable as an installed workspace member, not by path accident."""

from __future__ import annotations

from pathlib import Path

import pulse_ledger


def test_package_imports_from_its_src_tree():
    assert pulse_ledger.__file__ is not None
    pkg_path = Path(pulse_ledger.__file__).resolve()
    assert pkg_path.parent.name == "pulse_ledger"
    assert (pkg_path.parent / "py.typed").is_file()
