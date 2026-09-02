"""billing is importable as an installed workspace member, not by path accident."""

from __future__ import annotations

from pathlib import Path

import billing


def test_package_imports_from_its_src_tree() -> None:
    assert billing.__file__ is not None
    pkg_path = Path(billing.__file__).resolve()
    assert pkg_path.parent.name == "billing"
    assert (pkg_path.parent / "py.typed").is_file()
