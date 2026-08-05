"""Property test for the declarer's ordering core (task 4.2, design decision 7).

Scenario (verdict-declare): a shuffled batch declares monotonically and skips stale rows. For any
shuffled batch of verdict runs across subjects — including runs older than a subject's latest
declared `as_of`, whether that watermark was seeded by a prior run or raised mid-batch — the
declared order is `as_of`-monotonic per subject, every stale row is skipped and counted as
skipped-stale, and no stale row produces a declaration or an error.

The oracle is a few-line reference model over the same row sequence: track each subject's
high-water `as_of`; a row strictly below it is stale, anything else is submitted, and a submitted
duplicate of an already-submitted (subject, `as_of`) pair replays under D16. The implementation
must agree with it row for row, disposition for disposition — and the submitted-request log must
agree in aggregate (per-subject monotonicity, no stale submissions, final watermarks).

Determinism in CI: the `ci` hypothesis profile below sets `derandomize=True`, so the example
sequence derives from the test itself rather than a random seed, and `deadline=None` on both
profiles removes wall-clock flake — the two failure modes the work order names. All rows are
synthetic; no PHI.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import cast

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st
from pulse_core.client import PulseCoreClient
from verdict_relay.declarer import Declarer, RowDisposition

settings.register_profile("ci", derandomize=True, deadline=None, max_examples=200)
settings.register_profile("dev", deadline=None)
settings.load_profile("ci" if os.environ.get("CI") else "dev")

SUBJECT_TYPE_BY_VERDICT = {"billing_qualification": "billing_episode"}

#: A small subject pool and a coarse hour grid force the interesting collisions — same-subject
#: interleavings, duplicate (subject, as_of) pairs, and rows behind a seeded watermark.
SUBJECTS = ("episode-a", "episode-b", "episode-c")
BASE_INSTANT = datetime(2026, 8, 1, tzinfo=timezone.utc)
HOURS = st.integers(min_value=0, max_value=12)

#: One run is (subject, as_of hour); a batch is any list of them — hypothesis owns the shuffle.
RUNS = st.lists(st.tuples(st.sampled_from(SUBJECTS), HOURS), max_size=30)

#: Optional pre-seeded watermarks, as if a prior relay run had already declared these subjects.
SEEDED_WATERMARKS = st.dictionaries(st.sampled_from(SUBJECTS), HOURS)


def _as_of(hour: int) -> datetime:
    return BASE_INSTANT + timedelta(hours=hour)


def _row(subject: str, hour: int) -> dict[str, object]:
    return {
        "subject_id": subject,
        "verdict_type": "billing_qualification",
        "outcome": "positive",
        "reason": None,
        "rule_version": "rules-v3",
        "as_of": _as_of(hour).isoformat(),
        "lineage_ref": "dbt-run-2026-08-01T02",
        "computed_at": "2026-08-01T02:00:00+00:00",
    }


class ReplayAwareApi:
    """The command API faked at the client boundary, with D16 memory.

    A request whose idempotency key was already committed answers `replayed`; everything else
    commits. Request bodies are recorded so the test can assert on the declared order itself,
    not just the counters.
    """

    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []
        self._seen_keys: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        parsed: object = json.loads(request.content)
        assert isinstance(parsed, dict)
        body = cast("dict[str, object]", parsed)
        self.bodies.append(body)
        key = body["idempotency_key"]
        assert isinstance(key, str)
        already_committed = key in self._seen_keys
        self._seen_keys.add(key)
        event_id = f"e{len(self._seen_keys)}"
        return httpx.Response(201, json={"event_id": event_id, "replayed": already_committed})

    def client(self) -> PulseCoreClient:
        return PulseCoreClient(
            "http://ledger.test",
            writer_id="verdict-relay",
            token="unit-test-token",  # noqa: S106 — a fixture value, not a secret
            transport=httpx.MockTransport(self.handler),
            max_attempts=1,
        )


def _reference_dispositions(
    runs: list[tuple[str, int]],
    seeded: dict[str, int],
) -> list[RowDisposition]:
    """The oracle: stale below the watermark, replayed on a duplicate submission, else declared."""
    high_water: dict[str, int] = dict(seeded)
    submitted: set[tuple[str, int]] = set()
    expected: list[RowDisposition] = []
    for subject, hour in runs:
        watermark = high_water.get(subject)
        if watermark is not None and hour < watermark:
            expected.append(RowDisposition.SKIPPED_STALE)
            continue
        expected.append(RowDisposition.REPLAYED if (subject, hour) in submitted else RowDisposition.DECLARED)
        submitted.add((subject, hour))
        high_water[subject] = max(watermark, hour) if watermark is not None else hour
    return expected


@given(runs=RUNS, seeded=SEEDED_WATERMARKS)
def test_a_shuffled_batch_declares_monotonically_and_skips_stale_rows(
    runs: list[tuple[str, int]],
    seeded: dict[str, int],
) -> None:
    api = ReplayAwareApi()
    declarer = Declarer(
        api.client(),
        subject_type_by_verdict=SUBJECT_TYPE_BY_VERDICT,
        watermarks={subject: _as_of(hour).isoformat() for subject, hour in seeded.items()},
        sleep=lambda _seconds: None,
    )

    # No stale row errors: every row settles to a disposition, none raises.
    dispositions = [declarer.declare(_row(subject, hour)) for subject, hour in runs]

    expected = _reference_dispositions(runs, seeded)
    assert dispositions == expected

    # Every stale row is skipped and counted; declared/replayed tally the rest.
    assert declarer.counts.skipped_stale == expected.count(RowDisposition.SKIPPED_STALE)
    assert declarer.counts.declared == expected.count(RowDisposition.DECLARED)
    assert declarer.counts.replayed == expected.count(RowDisposition.REPLAYED)

    # No stale row produces a declaration: only declared/replayed rows reached the API.
    assert len(api.bodies) == declarer.counts.declared + declarer.counts.replayed

    # The declared order is as_of-monotonic per subject, read off the submitted requests.
    submitted_order: dict[str, list[str]] = {}
    for body in api.bodies:
        subject_key = body["subject_key"]
        effective_at = body["effective_at"]
        assert isinstance(subject_key, str)
        assert isinstance(effective_at, str)
        submitted_order.setdefault(subject_key, []).append(effective_at)
    for effective_ats in submitted_order.values():
        instants = [datetime.fromisoformat(value) for value in effective_ats]
        assert instants == sorted(instants)

    # The watermark ends at each subject's max as_of across the seed and every declared row.
    final_hours: dict[str, int] = dict(seeded)
    for subject, hour in runs:
        if hour >= final_hours.get(subject, hour):
            final_hours[subject] = hour
    assert declarer.watermarks == {subject: _as_of(hour).isoformat() for subject, hour in final_hours.items()}
