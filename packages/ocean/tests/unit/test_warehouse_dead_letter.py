"""warehouse-sync no longer holds an inline Kafka producer for dead-letter writes.

Task 4.13 (DNA-756) removes the bespoke `ocean.warehouse-dlq` write rather than
converting it: a batch the warehouse cannot accept leaves its offsets uncommitted
and is redelivered, and repeated failure reaches the consumer queue's own DLQ
(task 7.2). These tests pin the removal and the failure contract that replaces it.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect

import pytest
from utils import setup_service

setup_service("warehouse-sync")

import src.main as main


class _Cursor:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.executed: list[tuple[str, list[str]]] = []
        self.closed = False

    def execute(self, sql: str, params: list[str]) -> None:
        if self.fail:
            raise RuntimeError("snowflake rejected the batch")
        self.executed.append((sql, params))

    def close(self) -> None:
        self.closed = True


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor


def test_no_producer_symbols() -> None:
    """The inline producer and its dead-letter helper are gone."""
    for name in ("Producer", "_make_producer", "_publish_to_dlq"):
        assert not hasattr(main, name), f"{name} must not survive the migration"


def test_no_dead_letter_write_remains() -> None:
    """No code path publishes to the bespoke dead-letter topic."""
    source = inspect.getsource(main)
    assert ".produce(" not in source, "warehouse-sync must not write to a topic"


async def test_flush_batch_inserts_rows() -> None:
    cursor = _Cursor()
    batch = [(b'{"id": 1}', "ocean.clinical"), (b'{"id": 2}', "ocean.ops")]

    await main._flush_batch(_Conn(cursor), batch)

    sql, params = cursor.executed[0]
    assert "STREAMLINE.OCEAN_RAW.EVENTS" in sql
    assert params == ['{"id": 1}', "ocean.clinical", '{"id": 2}', "ocean.ops"]
    assert cursor.closed


async def test_flush_batch_empty_is_a_no_op() -> None:
    cursor = _Cursor()
    await main._flush_batch(_Conn(cursor), [])
    assert cursor.executed == []


async def test_flush_batch_raises_so_the_caller_does_not_commit() -> None:
    """A failed insert must surface, not be swallowed into a side channel."""
    cursor = _Cursor(fail=True)

    with pytest.raises(RuntimeError):
        await main._flush_batch(_Conn(cursor), [(b'{"id": 1}', "ocean.clinical")])

    assert cursor.closed, "the cursor is released even when the insert fails"


class _Log:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, event: str, **_kw: object) -> None:
        self.errors.append(event)


@pytest.fixture
def captured_log(monkeypatch: pytest.MonkeyPatch) -> _Log:
    stub = _Log()
    monkeypatch.setattr(main, "log", stub)
    return stub


async def test_a_dead_consumer_is_logged(captured_log: _Log) -> None:
    """A raising loop must not vanish silently now that a failed flush ends it."""

    async def _boom() -> None:
        raise RuntimeError("snowflake rejected the batch")

    task = asyncio.ensure_future(_boom())
    with contextlib.suppress(RuntimeError):
        await task
    main._log_consumer_exit(task)

    assert captured_log.errors == ["consumer_exited"]


async def test_a_cancelled_consumer_is_not_an_error(captured_log: _Log) -> None:
    async def _forever() -> None:
        await asyncio.sleep(60)

    task = asyncio.ensure_future(_forever())
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    main._log_consumer_exit(task)

    assert captured_log.errors == []
