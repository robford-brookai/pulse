"""Credential-material gate: no Mongo connection string with credentials, anywhere.

Repository-wide, over every git-tracked file, wired into `task test` via this
package's suite (spec: "Credential material cannot land in the tree"). The
pattern catches ``mongodb://`` and ``mongodb+srv://`` URIs carrying a
``user:password@`` credential segment; the regex source deliberately does not
match itself. On failure the assertion names offending *paths* only, never the
matched content, so the gate cannot leak what it exists to block.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: A mongodb/mongodb+srv URI whose authority section starts with `user:pass@`.
_CREDENTIAL_URI = re.compile(rb"mongodb(\+srv)?://[^@\s/'\"]+:[^@\s'\"]*@")


def _tracked_files() -> list[Path]:
    git = shutil.which("git")
    assert git is not None, "git not on PATH"
    out = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return sorted(_REPO_ROOT / name for name in out.decode().split("\0") if name)


def test_no_credential_bearing_mongo_uri_anywhere_in_the_tree() -> None:
    offenders = [
        path.relative_to(_REPO_ROOT)
        for path in _tracked_files()
        if path.is_file() and _CREDENTIAL_URI.search(path.read_bytes())
    ]
    assert offenders == [], f"credential-shaped Mongo URI found in: {[str(p) for p in offenders]}"


def test_the_gate_catches_what_it_exists_to_catch() -> None:
    """The pattern is live: synthetic credential-bearing URIs, assembled so the
    literal never appears in this file, must match; credential-free forms must not."""
    scheme_plain = "mongodb" + "://"
    scheme_srv = "mongodb+srv" + "://"
    assert _CREDENTIAL_URI.search(f"{scheme_plain}user:synthetic@host:27017/db".encode())
    assert _CREDENTIAL_URI.search(f"{scheme_srv}user:synthetic@cluster.example.net/".encode())
    assert not _CREDENTIAL_URI.search(f"{scheme_srv}cluster.example.net/".encode())
    assert not _CREDENTIAL_URI.search(b"host and user supplied separately, never a URI")
