"""`pulse_core.connector` re-exports every name it advertises (task 1.1, connector-kit spec:
"the kit's advertised surface resolves").

`test_connector_kit_all_names_resolve` (`tests/scaffold/cat10_devex.py`) checks the names in
`__all__` all resolve to *something*; this test checks the other half — a star-import actually
binds them, which is what a connector author relying on `from pulse_core.connector import *`
gets.

`test_guide_named_primitive_imports_from_root` and `test_reference_connectors_import_from_root`
(task 1.5, spec scenario: "Guide-named primitive imports from the root") pin the guide's own
rule — "Import from the package root, not the submodules" (`docs/connectors/authoring.md`) —
against both the specific primitive the guide names (`Jitter`) and every reference connector the
guide points to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pulse_core.connector as kit

ROOT = Path(__file__).resolve().parents[3]

#: Every connector the guide names as reference or prior art (`docs/connectors/authoring.md`,
#: "the reference implementation" and the direction table) — the root-import rule applies to all
#: of them, not only the one named "the" reference.
_REFERENCE_CONNECTOR_SRC_DIRS = (
    "packages/billing-connector/src",
    "packages/verdict-relay/src",
    "packages/consent-ingress/src",
    "packages/twenty-projection/src",
)


def test_star_import_binds_every_all_name():
    namespace: dict[str, object] = {}
    exec("from pulse_core.connector import *", namespace)  # noqa: S102 — asserting * semantics

    missing = [name for name in kit.__all__ if name not in namespace]
    assert missing == [], f"__all__ promises names a star-import never binds: {missing}"


def test_guide_named_primitive_imports_from_root():
    """Spec scenario: `from pulse_core.connector import Jitter` succeeds and `Jitter` is
    in `__all__` — the guide-named primitive resolves at the root, not only the submodule it is
    defined in."""
    namespace: dict[str, object] = {}
    exec("from pulse_core.connector import Jitter", namespace)  # noqa: S102

    assert "Jitter" in kit.__all__
    assert namespace["Jitter"] is kit.Jitter


def test_reference_connectors_import_from_root():
    """The guide's rule ("Import from the package root, not the submodules") applies to the
    reference connectors it points a connector author at, not only new code — a submodule import
    of a name the root already exports is exactly the drift the rule exists to catch."""
    submodule_import = re.compile(r"^from pulse_core\.connector\.\w+ import ", re.MULTILINE)
    offenders: list[str] = []
    for src_dir in _REFERENCE_CONNECTOR_SRC_DIRS:
        package_root = ROOT / src_dir
        if not package_root.is_dir():
            continue
        for path in sorted(package_root.rglob("*.py")):
            if submodule_import.search(path.read_text()):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], f"reference connector(s) import a kit submodule directly: {offenders}"
