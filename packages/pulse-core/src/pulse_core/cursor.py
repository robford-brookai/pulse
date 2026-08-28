"""Writer cursor — the JSON-native contract between a writer and its durable resume point.

`PUT/GET /writers/{writer_id}/cursor` (design decision 2) stores whatever a writer checkpoints as
opaque JSONB (`ledger.writer_state.cursor`, via `pulse_ledger.cursor`); the ledger never interprets
it. This module is the one place that opacity gets a boundary: a cursor SHALL be JSON-native,
because the crash/resume scenario the ledger-read spec describes only holds if what a writer reads
back is exactly what it wrote. A python value with no canonical JSON spelling (a `datetime`, a
`set`) would silently become something else the moment it crossed the wire, and a writer resuming
from that value would resume from a cursor it never wrote.

`cursor_path` is the other thing both sides need to agree on: the URL a writer's cursor lives at,
named once so the route (`pulse_ledger.api`) and the future client (`pulse_core.client`, task 4.3)
cannot spell it differently.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

#: `{writer_id}` — a FastAPI/Starlette path template, shared verbatim by the route and any caller
#: building the URL by hand.
CURSOR_PATH_TEMPLATE = "/writers/{writer_id}/cursor"


def cursor_path(writer_id: str) -> str:
    """The URL a writer's cursor lives at."""
    return CURSOR_PATH_TEMPLATE.format(writer_id=writer_id)


class InvalidCursorError(ValueError):
    """A cursor value has no canonical JSON spelling, so it would not round-trip unchanged.

    Carries the path to the offending value and its type — never the value, which may hold PHI
    once C1 clears.
    """

    def __init__(self, path: str, type_name: str) -> None:
        self.path = path
        self.type_name = type_name
        super().__init__(f"{path} is a {type_name}, which is not JSON-native and cannot round-trip as a cursor")


def validate_cursor(cursor: object) -> dict[str, object]:
    """Return `cursor` as a plain JSON-native dict, or raise `InvalidCursorError`.

    A cursor has no required shape — a mart's watermark, a batch offset, a resume token are all a
    writer's own business — only a requirement that every value in it is one JSON can represent
    without loss: `None`, `bool`, `int`, a finite `float`, `str`, or a mapping/sequence of those.
    `cursor` is typed `object` rather than `Mapping` because the caller has not necessarily checked
    that yet — this is the boundary that checks it.
    """
    if not isinstance(cursor, Mapping):
        raise InvalidCursorError("cursor", type(cursor).__name__)
    result = _canonical(cursor, "cursor")
    assert isinstance(result, dict)  # noqa: S101 — `_canonical` returns a dict for any Mapping input
    return result


def _canonical(value: object, path: str) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidCursorError(path, "non-finite float")
        return value
    if isinstance(value, Mapping):
        canonical: dict[str, object] = {}
        for key, member in value.items():
            if not isinstance(key, str):
                raise InvalidCursorError(path, f"mapping with a {type(key).__name__} key")
            canonical[key] = _canonical(member, f"{path}.{key}")
        return canonical
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical(member, f"{path}[{index}]") for index, member in enumerate(value)]
    raise InvalidCursorError(path, type(value).__name__)
