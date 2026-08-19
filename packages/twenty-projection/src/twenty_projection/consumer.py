"""Consumer entrypoint stub — the queue loop lands in twenty-projection task 2.3.

Exists so `task projection:consume TARGET=<t>` resolves to a named, honest failure
instead of an ImportError. Holds no credential resolution, no transport, and no
ledger access of any kind.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Fail by name until the wave-1 consumer loop replaces this stub."""
    print(
        "twenty-projection consumer is not implemented yet (twenty-projection task 2.3)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
