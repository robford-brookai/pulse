"""Test-only access to `fixtures/twenty/` — the synthetic Twenty webhook payloads.

`fixtures/twenty/README.md` names each case; this module is the one place a test turns a case name
into bytes, a parsed body, or a signed request. No test should open a fixture path directly or
recompute an HMAC by hand — both duplicate something this module already owns, and a duplicated
HMAC recipe is exactly the kind of thing that quietly drifts from `pulse_ledger.auth.sign`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pulse_ledger.auth import SIGNATURE_FRESHNESS, SIGNATURE_HEADER, TIMESTAMP_HEADER, sign

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "twenty"

#: Every named case, in the order `README.md` documents them. A name outside this tuple is a typo,
#: not a fixture that has not been written yet — `fixture_path` raises rather than guessing.
FIXTURE_NAMES: tuple[str, ...] = (
    "legal_drag",
    "illegal_drag",
    "redelivery_duplicate",
    "missing_canonical_id",
    "noop_create",
    "noop_delete",
    "noop_non_status_update",
    "noop_unmapped_object",
    "malformed_body",
)


class UnknownFixtureError(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no Twenty webhook fixture named {name!r}; known names: {list(FIXTURE_NAMES)}")


#: `malformed_body` is deliberately not valid JSON, so it is not named `.json` — pre-commit's
#: `check-json`/`pretty-format-json` hooks would otherwise refuse to let it be committed at all.
_MALFORMED_EXTENSION_NAME = "malformed_body"


def fixture_path(name: str) -> Path:
    """The path for a named case. Raises `UnknownFixtureError` for anything not in `FIXTURE_NAMES`."""
    if name not in FIXTURE_NAMES:
        raise UnknownFixtureError(name)
    extension = "txt" if name == _MALFORMED_EXTENSION_NAME else "json"
    return FIXTURES_DIR / f"{name}.{extension}"


def load_fixture_bytes(name: str) -> bytes:
    """The fixture's raw bytes, exactly as a webhook body arrives — sign these, not a re-dump."""
    return fixture_path(name).read_bytes()


def load_fixture_json(name: str) -> object:
    """The fixture parsed as JSON.

    Raises `json.JSONDecodeError` for `malformed_body` by design: that fixture's whole purpose is
    a body that does not parse, and a caller that wants it as JSON is asking the wrong question.
    """
    return json.loads(load_fixture_bytes(name))


SignatureKind = Literal["valid", "tampered", "stale"]


def sign_fixture(secret: str, body: bytes, *, now: datetime, kind: SignatureKind = "valid") -> dict[str, str]:
    """Signature headers for `body`, via `pulse_ledger.auth.sign` — never a hand-rolled HMAC.

    - `valid`: signed over `body` itself, timestamped at `now` — inside the freshness window.
    - `tampered`: signed over a body that is *not* `body`, so the returned signature will not
      verify against `body` when a test posts it unchanged — "the body does not match its
      signature," not a corrupted hex string `hmac.compare_digest` would catch just the same.
    - `stale`: signed over `body` correctly, but timestamped just past `SIGNATURE_FRESHNESS` — a
      correctly signed request outside the freshness window.
    """
    if kind == "valid":
        timestamp = str(int(now.timestamp()))
        return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(secret, timestamp, body)}
    if kind == "tampered":
        timestamp = str(int(now.timestamp()))
        return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(secret, timestamp, body + b" ")}
    if kind == "stale":
        stale_at = now - SIGNATURE_FRESHNESS - timedelta(seconds=1)
        timestamp = str(int(stale_at.timestamp()))
        return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: sign(secret, timestamp, body)}
    msg = f"unknown signature kind: {kind!r}"
    raise ValueError(msg)
