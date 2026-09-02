"""Per-subject committed history — the URL both sides of the read agree on.

`GET /subjects/{subject_type}/{subject_key}/events` (pulse-demo-closeout design decision 5) is the
ledger's replay surface: the committed events for one subject, in ledger sequence, as the same
envelopes the relay publishes. It exists so a projection can be repainted from the journal without
holding a ledger database credential — the rebuild reads it over HTTP under the credential it
already writes with.

The path lives here for the same reason `cursor.CURSOR_PATH_TEMPLATE` does: the route
(`pulse_ledger.api`) and the client (`pulse_core.client`) must not be able to spell it differently.
"""

from __future__ import annotations

from urllib.parse import quote

#: A FastAPI/Starlette path template, shared verbatim by the route and any caller building the URL.
SUBJECT_HISTORY_PATH_TEMPLATE = "/subjects/{subject_type}/{subject_key}/events"

#: Events returned per request when a caller names no page size. A subject's history is bounded by
#: how often its state changes, so this pages a pathological subject rather than a typical one.
DEFAULT_HISTORY_PAGE_SIZE = 500

#: The largest page the route will serve. A caller asking for more gets this, not an error: the
#: cap exists to bound one response, and paging past it is the caller's ordinary path anyway.
MAX_HISTORY_PAGE_SIZE = 1000


def subject_history_path(subject_type: str, subject_key: str) -> str:
    """The URL one subject's committed history lives at.

    Both segments are percent-encoded with no safe characters, because a `subject_key` is opaque to
    everything but the producer that minted it: a `?`, `#`, or `&` in a key would otherwise start a
    query string or a fragment and silently address a different subject.

    A key containing a literal `/` has no URL under this route — the path template matches one
    segment, and a percent-encoded slash is decoded before routing. No producer mints such a key
    (they are UUIDs and opaque tokens), and a route that could not tell `a/b` from a nested path is
    the wrong place to start.
    """
    return SUBJECT_HISTORY_PATH_TEMPLATE.format(
        subject_type=quote(subject_type, safe=""),
        subject_key=quote(subject_key, safe=""),
    )
