"""`pulse_core.connector` re-exports every name it advertises (task 1.1, connector-kit spec:
"the kit's advertised surface resolves").

`test_connector_kit_all_names_resolve` (`tests/scaffold/cat10_devex.py`) checks the names in
`__all__` all resolve to *something*; this test checks the other half — a star-import actually
binds them, which is what a connector author relying on `from pulse_core.connector import *`
gets.
"""

from __future__ import annotations

import pulse_core.connector as kit


def test_star_import_binds_every_all_name():
    namespace: dict[str, object] = {}
    exec("from pulse_core.connector import *", namespace)  # noqa: S102 — asserting * semantics

    missing = [name for name in kit.__all__ if name not in namespace]
    assert missing == [], f"__all__ promises names a star-import never binds: {missing}"
