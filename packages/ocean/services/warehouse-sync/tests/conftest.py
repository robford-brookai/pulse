"""Test harness for warehouse-sync: fakes, stage ordering, and the run log.

Stage machinery (task 5.9 rider)
--------------------------------
The suite runs a stage at a time, in a fixed order, and leaves a durable,
diffable record of each run:

- Every test carries exactly one MECE-category marker; ``-m <category>`` runs
  exactly that stage (e.g. ``pytest -m duplicates``).
- Stages have ordered identifiers (S1..S7). Collection is sorted by stage, so
  a run always executes S1 before S2. ``--resume-from=S4-reordering`` skips
  every stage that precedes S4, so a run can pick up after a failure.
- ``--run-log=PATH`` writes a JSON record of the run: per stage, its
  identifier, outcome, duration band, and the batch/cursor state each test
  observed (via the ``stage_log`` fixture). The log is normalised for
  diffing: no wall-clock timestamps, no random identifiers, durations
  bucketed into coarse bands, keys and lists deterministically ordered.

Fakes
-----
``FakeSnowflakeConnection`` emulates exactly the statement ``_flush_batch``
issues: a MERGE keyed on ``data:event_id`` that inserts when not matched and
never updates, with within-batch dedup (the QUALIFY clause). ``ScriptedSqsClient``
plays back a scripted sequence of receive_message results, advancing a fake
monotonic clock per step, and records deletions. A shared ``call log`` gives
tests the cross-fake operation order (receive/merge/delete).

No PHI: every fixture event is synthetic (``make_message``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

# --------------------------------------------------------------------------
# Stage registry — the ordered MECE taxonomy. test_warehouse_sync.py states
# what each category covers; this table is what the plugin machinery keys on.
# --------------------------------------------------------------------------

STAGES: list[tuple[str, str, str]] = [
    ("S1-ordering", "ordering", "receive/flush/delete ordering"),
    ("S2-batching", "batching", "batch accumulation and the flush window"),
    ("S3-duplicates", "duplicates", "duplicate redelivery yields no second row"),
    ("S4-reordering", "reordering", "delivery order does not change table contents"),
    ("S5-redrive", "redrive", "failed batches redeliver and converge"),
    ("S6-cursor", "cursor", "receipt-handle (cursor) handling on the failure path"),
    ("S7-shutdown", "shutdown", "shutdown with a partial batch"),
]

_MARKER_TO_STAGE = {marker: stage_id for stage_id, marker, _ in STAGES}
_STAGE_ORDER = {stage_id: i for i, (stage_id, _, _) in enumerate(STAGES)}


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--run-log",
        default=None,
        help="Path to write the per-stage run log (JSON, normalised for diffing).",
    )
    parser.addoption(
        "--resume-from",
        default=None,
        metavar="STAGE_ID",
        help="Skip every stage ordered before this one (e.g. S4-reordering).",
    )


def pytest_configure(config: Any) -> None:
    for stage_id, marker, description in STAGES:
        config.addinivalue_line("markers", f"{marker}: {stage_id} — {description}")
    config._stage_records = {}  # nodeid -> record dict
    config._stage_observations = {}  # nodeid -> observation dict
    resume = config.getoption("--resume-from")
    if resume is not None and resume not in _STAGE_ORDER:
        known = ", ".join(stage_id for stage_id, _, _ in STAGES)
        raise pytest.UsageError(f"--resume-from={resume!r} is not a stage; stages are: {known}")


def _stage_of(item: Any) -> str:
    stages = [_MARKER_TO_STAGE[m.name] for m in item.iter_markers() if m.name in _MARKER_TO_STAGE]
    if len(stages) != 1:
        raise pytest.UsageError(
            f"{item.nodeid} carries {len(stages)} MECE-category markers; every test "
            "must carry exactly one so it occupies exactly one taxonomy cell."
        )
    return stages[0]


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    items.sort(key=lambda item: (_STAGE_ORDER[_stage_of(item)], item.nodeid))
    resume = config.getoption("--resume-from")
    if resume is None:
        return
    threshold = _STAGE_ORDER[resume]
    for item in items:
        stage = _stage_of(item)
        if _STAGE_ORDER[stage] < threshold:
            item.add_marker(pytest.mark.skip(reason=f"{stage} precedes --resume-from={resume}"))


def _duration_band(seconds: float) -> str:
    """Coarse, diff-stable stand-in for a wall-clock duration."""
    if seconds < 1.0:
        return "sub-second"
    if seconds < 10.0:
        return "1-10s"
    return "over-10s"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Any, call: Any) -> Any:
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" and not (report.when == "setup" and report.skipped):
        return
    item.config._stage_records[item.nodeid] = {
        "stage": _stage_of(item),
        "outcome": report.outcome,
        "duration_band": _duration_band(report.duration),
    }


def pytest_sessionfinish(session: Any) -> None:
    path = session.config.getoption("--run-log")
    if path is None:
        return
    records = session.config._stage_records
    observations = session.config._stage_observations
    stages = []
    for stage_id, marker, description in STAGES:
        tests = []
        for nodeid in sorted(records):
            rec = records[nodeid]
            if rec["stage"] != stage_id:
                continue
            entry = {
                "id": nodeid,
                "outcome": rec["outcome"],
                "duration_band": rec["duration_band"],
            }
            if nodeid in observations:
                entry["observed"] = observations[nodeid]
            tests.append(entry)
        outcomes = {t["outcome"] for t in tests}
        if not tests:
            stage_outcome = "not-run"
        elif "failed" in outcomes:
            stage_outcome = "failed"
        elif outcomes == {"skipped"}:
            stage_outcome = "skipped"
        else:
            stage_outcome = "passed"
        stages.append({
            "stage": stage_id,
            "marker": marker,
            "description": description,
            "outcome": stage_outcome,
            "tests": tests,
        })
    log_doc = {"suite": "warehouse-sync-mece", "stages": stages}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log_doc, f, indent=2, sort_keys=True)
        f.write("\n")


@pytest.fixture
def stage_log(request: Any) -> StageObserver:
    """Lets a test record the batch/cursor state it observed, for the run log."""
    return StageObserver(request.config._stage_observations, request.node.nodeid)


class StageObserver:
    def __init__(self, sink: dict[str, Any], nodeid: str) -> None:
        self._sink = sink
        self._nodeid = nodeid

    def observe(self, **state: Any) -> None:
        self._sink.setdefault(self._nodeid, {}).update(state)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeClock:
    """Deterministic stand-in for time.monotonic."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCursor:
    def __init__(self, conn: FakeSnowflakeConnection) -> None:
        self._conn = conn
        self.closed = False

    def execute(self, sql: str, params: list[str]) -> None:
        conn = self._conn
        conn.merge_attempts += 1
        assert "MERGE INTO" in sql and "WHEN NOT MATCHED THEN INSERT" in sql, (
            "warehouse-sync no longer issues a MERGE...WHEN NOT MATCHED INSERT; "
            "this fake (and the duplicate-safety property) emulate that exact statement"
        )
        assert "QUALIFY ROW_NUMBER() OVER (PARTITION BY data:event_id" in sql
        if conn.fail_next_merges > 0:
            conn.fail_next_merges -= 1
            raise RuntimeError("synthetic snowflake failure")
        pairs = [(params[i], params[i + 1]) for i in range(0, len(params), 2)]
        seen_in_batch: set[str] = set()
        for data_json, domain in pairs:
            data = json.loads(data_json)
            event_id = data["event_id"]
            if event_id in seen_in_batch:  # QUALIFY: one source row per event_id
                continue
            seen_in_batch.add(event_id)
            if event_id in conn.table:  # ON ... WHEN NOT MATCHED only: never update
                continue
            conn.table[event_id] = {"data": data, "domain": domain}
        conn.call_log.append(("merge", len(pairs)))

    def close(self) -> None:
        self.closed = True


class FakeSnowflakeConnection:
    """In-memory OCEAN_RAW.EVENTS with the MERGE-on-event_id contract."""

    def __init__(self, call_log: list[Any] | None = None) -> None:
        self.table: dict[str, dict[str, Any]] = {}
        self.call_log: list[Any] = call_log if call_log is not None else []
        self.merge_attempts = 0
        self.fail_next_merges = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class ScriptedSqsClient:
    """Plays back scripted receive_message results and records deletions.

    Each script step is a dict: ``messages`` (list of SQS message dicts),
    ``advance`` (seconds to move the fake clock before returning). When the
    script is exhausted the next receive raises CancelledError — the same
    signal a real shutdown delivers to the loop's await.
    """

    def __init__(
        self,
        script: list[dict[str, Any]],
        clock: FakeClock,
        call_log: list[Any] | None = None,
    ) -> None:
        self.script = list(script)
        self.clock = clock
        self.call_log: list[Any] = call_log if call_log is not None else []
        self.deleted: list[str] = []
        self.delete_calls: list[list[str]] = []
        self.fail_next_deletes = 0
        self.partial_fail_next_deletes = 0
        self.aexit_called = False

    async def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        if not self.script:
            raise asyncio.CancelledError
        step = self.script.pop(0)
        self.clock.advance(step.get("advance", 0.0))
        self.call_log.append(("receive", len(step.get("messages", []))))
        return {"Messages": step.get("messages", [])}

    async def delete_message_batch(self, QueueUrl: str, Entries: list[dict[str, str]]) -> dict[str, Any]:
        receipts = [e["ReceiptHandle"] for e in Entries]
        if self.fail_next_deletes > 0:
            self.fail_next_deletes -= 1
            raise RuntimeError("synthetic sqs delete failure")
        if self.partial_fail_next_deletes > 0:
            self.partial_fail_next_deletes -= 1
            ok, lost = receipts[:-1], receipts[-1:]
            self.deleted.extend(ok)
            self.delete_calls.append(receipts)
            self.call_log.append(("delete", len(receipts)))
            return {
                "Successful": [{"Id": str(i)} for i in range(len(ok))],
                "Failed": [{"Id": str(len(ok)), "SenderFault": False} for _ in lost],
            }
        self.deleted.extend(receipts)
        self.delete_calls.append(receipts)
        self.call_log.append(("delete", len(receipts)))
        return {"Successful": [{"Id": str(i)} for i in range(len(receipts))], "Failed": []}

    async def __aexit__(self, *exc: Any) -> None:
        self.aexit_called = True


def make_message(event_id: str, *, domain: str = "alerts", delivery: int = 0) -> dict[str, Any]:
    """A synthetic EventBridge→SQS message. ``delivery`` distinguishes the
    receipt handle of a redelivery from the original's — as SQS does."""
    envelope = {
        "event_id": event_id,
        "domain": domain,
        "payload": {"synthetic": True, "name": f"fixture-{event_id}"},
    }
    return {
        "ReceiptHandle": f"rh-{event_id}-d{delivery}",
        "Body": json.dumps({"detail-type": domain, "detail": envelope}),
    }


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, clock: FakeClock):
    """Wire the fakes into src.main and return a factory for consume-loop runs."""
    import src.main as main

    call_log: list[Any] = []
    sf = FakeSnowflakeConnection(call_log)
    monkeypatch.setattr(main, "_connect_snowflake", lambda: sf)
    monkeypatch.setattr(main.time, "monotonic", clock.monotonic)

    class Harness:
        def __init__(self) -> None:
            self.main = main
            self.sf = sf
            self.call_log = call_log
            self.clock = clock

        def client(self, script: list[dict[str, Any]]) -> ScriptedSqsClient:
            return ScriptedSqsClient(script, clock, call_log)

        async def run(self, client: ScriptedSqsClient) -> None:
            await main._consume_loop("https://sqs.test/000000000000/warehouse-sync", sqs_client=client)

        async def run_to_shutdown(self, client: ScriptedSqsClient) -> None:
            with pytest.raises(asyncio.CancelledError):
                await self.run(client)

    return Harness()
