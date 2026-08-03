"""pulse_core is importable as an installed workspace member, not by path accident."""

from __future__ import annotations

from pathlib import Path

import pulse_core


def test_package_imports_from_its_src_tree():
    assert pulse_core.__file__ is not None
    pkg_path = Path(pulse_core.__file__).resolve()
    assert pkg_path.parent.name == "pulse_core"
    assert (pkg_path.parent / "py.typed").is_file()
